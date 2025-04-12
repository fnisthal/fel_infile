import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("delete from ir_model_data where module = 'fel_infile' and model = 'ir.ui.view' and name like '%view%';")
    _logger.info("Referencias a vistas viejas borradas")