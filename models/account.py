# -*- encoding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_round

from datetime import datetime
import base64
from lxml import etree
import requests
import re

#from import XMLSigner

import logging

class AccountMove(models.Model):
    _inherit = "account.move"

    pdf_fel = fields.Char('PDF FEL', copy=False)
    
    def _post(self, soft=True):
        if self.certificar():
            return super(AccountMove, self)._post(soft)

    def certificar(self):
        for factura in self:
            if factura.requiere_certificacion('infile'):
                self.ensure_one()
                factura.error_pre_validacion()

                try:
                    if factura.company_id.buscar_nombre_para_dte_fel and not factura.partner_id.nombre_facturacion_fel:
                        factura.partner_id.nombre_facturacion_fel = factura.partner_id._datos_sat(factura.company_id, factura.partner_id.vat)['nombre']
                    
                    dte = factura.dte_documento()
                    xmls = etree.tostring(dte, encoding="UTF-8")
                    logging.warning(xmls.decode("utf-8"))
                    xmls_base64 = base64.b64encode(xmls)
                    
                    headers = { "Content-Type": "application/json" }
                    data = {
                        "llave": factura.company_id.token_firma_fel,
                        "archivo": xmls_base64.decode("utf-8"),
                        "codigo": factura.company_id.vat.replace('-',''),
                        "alias": factura.company_id.usuario_fel,
                    }
                    logging.warning(data)
                    r = requests.post('https://signer-emisores.feel.com.gt/sign_solicitud_firmas/firma_xml', json=data, headers=headers)
                    logging.warning(r.text)
                    firma_json = r.json()
                    if firma_json and "resultado" in firma_json and firma_json["resultado"]:
                        identificador = factura.journal_id.code+str(factura.id)
                        if factura.contingencia_fel:
                            identificador = factura.journal_id.code+'(CONT)'+str(factura.numero_acceso_fel)

                        headers = {
                            "USUARIO": factura.company_id.usuario_fel,
                            "LLAVE": factura.company_id.clave_fel,
                            "IDENTIFICADOR": identificador,
                            "Content-Type": "application/json",
                        }
                        data = {
                            "nit_emisor": factura.company_id.vat.replace('-',''),
                            "correo_copia": factura.company_id.email,
                            "xml_dte": firma_json["archivo"]
                        }
                        logging.warning(headers)
                        logging.warning(data)
                        r = requests.post("https://certificador.feel.com.gt/fel/certificacion/v2/dte/", json=data, headers=headers)
                        logging.warning(r.text)
                        certificacion_json = r.json()
                        if certificacion_json["resultado"]:
                            factura.firma_fel = certificacion_json["uuid"]
                            factura.ref = str(certificacion_json["serie"])+"-"+str(certificacion_json["numero"])
                            factura.serie_fel = certificacion_json["serie"]
                            factura.numero_fel = certificacion_json["numero"]
                            factura.documento_xml_fel = xmls_base64
                            factura.resultado_xml_fel = certificacion_json["xml_certificado"]
                            factura.pdf_fel = "https://report.feel.com.gt/ingfacereport/ingfacereport_documento?uuid="+certificacion_json["uuid"]
                            factura.certificador_fel = "infile"
                        else:
                            factura.error_certificador(str(certificacion_json["descripcion_errores"]))
                            
                    else:
                        factura.error_certificador(r.text)
                except Exception as e:
                    factura.error_certificador(str(e))

        return True
        
    def button_cancel(self):
        result = super(AccountMove, self).button_cancel()
        for factura in self:
            if factura.requiere_certificacion() and factura.firma_fel:
                                    
                import http.client
                logging.basicConfig(level=logging.DEBUG)
                httpclient_logger = logging.getLogger("http.client")
                def httpclient_log(*args):
                    httpclient_logger.log(logging.DEBUG, " ".join(args))

                http.client.print = httpclient_log
                http.client.HTTPConnection.debuglevel = 1
                    
                dte = factura.dte_anulacion()
                
                xmls = etree.tostring(dte, encoding="UTF-8")
                xmls_base64 = base64.b64encode(xmls)
                logging.warning(xmls)

                headers = { "Content-Type": "application/json" }
                data = {
                    "llave": factura.company_id.token_firma_fel,
                    "archivo": xmls_base64.decode("utf-8"),
                    "codigo": factura.company_id.vat.replace('-',''),
                    "alias": factura.company_id.usuario_fel,
                    "es_anulacion": "S",
                }
                r = requests.post('https://signer-emisores.feel.com.gt/sign_solicitud_firmas/firma_xml', json=data, headers=headers)
                logging.warn(r.text)
                firma_json = r.json()
                if firma_json["resultado"]:
                    identificador = factura.journal_id.code+str(factura.id)
                    if factura.contingencia_fel:
                        identificador = factura.journal_id.code+'(CONT)'+str(factura.numero_acceso_fel)

                    headers = {
                        "USUARIO": factura.company_id.usuario_fel,
                        "LLAVE": factura.company_id.clave_fel,
                        "IDENTIFICADOR": identificador,
                        "Content-Type": "application/json",
                    }
                    data = {
                        "nit_emisor": factura.company_id.vat.replace('-',''),
                        "correo_copia": factura.company_id.email,
                        "xml_dte": firma_json["archivo"]
                    }
                    r = requests.post("https://certificador.feel.com.gt/fel/anulacion/v2/dte/", json=data, headers=headers)
                    logging.warn(r.text)
                    certificacion_json = r.json()
                    if not certificacion_json["resultado"]:
                        raise UserError(str(certificacion_json["descripcion_errores"]))
                else:
                    raise UserError(r.text)

class AccountJournal(models.Model):
    _inherit = "account.journal"

class ResCompany(models.Model):
    _inherit = "res.company"

    usuario_fel = fields.Char('Usuario FEL')
    clave_fel = fields.Char('Clave FEL')
    token_firma_fel = fields.Char('Token Firma FEL')
    certificador_fel = fields.Selection(selection_add=[('infile', 'Infile')])
    buscar_nombre_para_dte_fel = fields.Boolean('Buscar nombre en SAT para enviar al certificador')

class Partner(models.Model):
    _inherit = 'res.partner'
    
    def _datos_sat(self, company, vat):
        if vat:
            headers = { "Content-Type": "application/json" }
            data = {
                "emisor_codigo": company.usuario_fel,
                "emisor_clave": company.clave_fel,
                "nit_consulta": vat.replace('-',''),
            }
            r = requests.post('https://consultareceptores.feel.com.gt/rest/action', json=data, headers=headers)
            logging.warning(r.text)
            if r and r.json():
                return r.json()
                
        return {'nombre': '', 'nit': ''}
