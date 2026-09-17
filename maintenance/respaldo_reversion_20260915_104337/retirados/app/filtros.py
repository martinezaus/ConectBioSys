from PyQt6.QtCore import QDate, pyqtSignal
from PyQt6.QtWidgets import QWidget,QFormLayout,QComboBox,QDateEdit,QLineEdit,QPushButton

class FiltrosMarcaciones(QWidget):
    consultar = pyqtSignal(dict)
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setStyleSheet("QLabel { color: #dce2f0; }")
        form=QFormLayout(self)
        self.origen=QComboBox();self.origen.addItems(['Reloj','Base local']);form.addRow('Origen',self.origen)
        self.modo=QComboBox();self.modo.addItems(['Mes anterior','Últimos 7 días','Tarjeta + rango','Rango personalizado']);form.addRow('Filtro',self.modo)
        self.desde=QDateEdit(QDate.currentDate());self.hasta=QDateEdit(QDate.currentDate())
        for field in (self.desde,self.hasta):field.setCalendarPopup(True);field.setDisplayFormat('dd/MM/yyyy')
        form.addRow('Desde',self.desde);form.addRow('Hasta',self.hasta)
        self.tarjeta=QLineEdit();form.addRow('Tarjeta / ID en el reloj',self.tarjeta)
        buscar=QPushButton('Consultar / descargar');buscar.clicked.connect(self._consultar);form.addRow(buscar)
        self.modo.currentIndexChanged.connect(self._modo_cambio);self._modo_cambio()
    def _modo_cambio(self):
        custom=self.modo.currentIndex()>=2
        if not custom:
            from app.servicios import rango_filtro
            desde,hasta,_=rango_filtro(self.modo.currentIndex())
            self.desde.setDate(QDate.fromString(desde,'yyyy-MM-dd'))
            self.hasta.setDate(QDate.fromString(hasta,'yyyy-MM-dd'))
        self.desde.setEnabled(custom);self.hasta.setEnabled(custom)
        self.tarjeta.setEnabled(self.modo.currentIndex()==2)
    def _consultar(self):
        self.consultar.emit({'origen':self.origen.currentIndex(),'modo':self.modo.currentIndex(),
                             'desde':self.desde.date().toPyDate(),'hasta':self.hasta.date().toPyDate(),
                             'tarjeta':self.tarjeta.text().strip() if self.modo.currentIndex()==2 else None})
