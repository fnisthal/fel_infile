# -*- encoding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

import base64
from lxml import etree
import requests

import logging
_logger = logging.getLogger(__name__)

UNIFIED_ENDPOINT = 'https://certificador.feel.com.gt/fel/procesounificado/transaccion/v2/xml'


class AccountMove(models.Model):
    _inherit = "account.move"

    pdf_fel = fields.Char('PDF FEL', copy=False)

    def _post(self, soft=True):
        if self.env.context.get('skip_fel_certification'):
            return super(AccountMove, self)._post(soft)
        if self.certificar():
            return super(AccountMove, self)._post(soft)

    def _headers_certificador_fel(self, identificador):
        self.ensure_one()
        factura = self
        return {
            "UsuarioFirma": factura.company_id.usuario_fel,
            "LlaveFirma": factura.company_id.token_firma_fel,
            "UsuarioApi": factura.company_id.usuario_fel,
            "LlaveApi": factura.company_id.clave_fel,
            "identificador": identificador,
            "Content-Type": "application/xml",
        }

    def _identificador_fel(self):
        self.ensure_one()
        factura = self
        if factura.uuid_pos_fel:
            return factura.uuid_pos_fel
        return factura.journal_id.code + '-' + str(factura.id)

    def certificar(self):
        facturas_a_certificar = self.filtered(lambda f: f.requiere_certificacion('infile'))
        diarios_sin_error_en_historial = facturas_a_certificar.filtered(lambda f: not f.journal_id.error_en_historial_fel)

        if len(facturas_a_certificar) > 1 and len(diarios_sin_error_en_historial) > 0:
            raise ValidationError(_('No se puede certificar más de una factura si no está activa la opción de "Error FEL en historial" en todos los diarios.'))

        for factura in facturas_a_certificar:
            if factura.error_pre_validacion():
                continue

            try:
                if factura.company_id.buscar_nombre_para_dte_fel and not factura.partner_id.nombre_facturacion_fel:
                    factura.partner_id.nombre_facturacion_fel = factura.partner_id.obtener_datos_facturacion_fel(factura.partner_id.vat)['nombre']

                dte = factura.dte_documento()
                xmls = etree.tostring(dte, encoding="utf-8", xml_declaration=True)
                xmls_base64 = base64.b64encode(xmls)

                identificador = factura._identificador_fel()
                headers = factura._headers_certificador_fel(identificador)
                _logger.info('Certificando factura %s (identificador=%s)', factura.id, identificador)

                r = requests.post(UNIFIED_ENDPOINT, data=xmls, headers=headers)
                _logger.info(r.text)
                resultado_json = r.json()

                if resultado_json and "resultado" in resultado_json and resultado_json["resultado"]:
                    factura.firma_fel = resultado_json["uuid"]
                    factura.ref = str(resultado_json["serie"])+"-"+str(resultado_json["numero"])
                    factura.serie_fel = resultado_json["serie"]
                    factura.numero_fel = resultado_json["numero"]
                    factura.documento_xml_fel = xmls_base64
                    factura.resultado_xml_fel = resultado_json["xml_certificado"]
                    factura.pdf_fel = "https://report.feel.com.gt/ingfacereport/ingfacereport_documento?uuid="+resultado_json["uuid"]
                    factura.certificador_fel = "infile"
                else:
                    factura.error_certificador(str(resultado_json.get("descripcion_errores") or r.text))
            except Exception as e:
                factura.error_certificador(str(e))

        return True

    def _anular_fel_certificador(self):
        self.ensure_one()
        factura = self

        if not factura.requiere_certificacion('infile'):
            return super(AccountMove, self)._anular_fel_certificador()

        dte = factura.dte_anulacion()
        xmls = etree.tostring(dte, encoding="utf-8", xml_declaration=True)
        xmls_base64 = base64.b64encode(xmls)

        identificador = factura._identificador_fel()
        headers = factura._headers_certificador_fel(identificador)
        _logger.info('Anulando factura %s (identificador=%s)', factura.id, identificador)

        r = requests.post(UNIFIED_ENDPOINT, data=xmls, headers=headers)
        _logger.info(r.text)
        resultado_json = r.json()

        if not resultado_json or not resultado_json.get("resultado"):
            raise UserError(str((resultado_json or {}).get("descripcion_errores") or r.text))

        return {
            'documento_xml_fel': xmls_base64,
            'documento_xml_fel_name': 'documento_anulacion_fel.xml',
            'resultado_xml_fel': resultado_json.get("xml_certificado") or base64.b64encode(r.text.encode("utf-8")),
            'resultado_xml_fel_name': 'resultado_anulacion_fel.xml',
        }

class AccountJournal(models.Model):
    _inherit = "account.journal"

class ResCompany(models.Model):
    _inherit = "res.company"

    usuario_fel = fields.Char('Usuario FEL')
    clave_fel = fields.Char('Llave API FEL')
    token_firma_fel = fields.Char('Llave Firma FEL')
    certificador_fel = fields.Selection(selection_add=[('infile', 'Infile')])
    buscar_nombre_para_dte_fel = fields.Boolean('Buscar nombre en SAT para enviar al certificador')
