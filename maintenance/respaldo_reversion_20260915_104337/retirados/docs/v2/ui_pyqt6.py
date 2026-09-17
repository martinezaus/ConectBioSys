"""Vista de referencia PyQt6. Sus señales se conectan a los servicios del diseño.
No ejecuta descargas, borrados ni conexiones por sí sola.
"""
from PyQt6.QtCore import QDate, pyqtSignal
from PyQt6.QtWidgets import (QWidget,QTabWidget,QFormLayout,QVBoxLayout,QHBoxLayout,
    QLineEdit,QComboBox,QSpinBox,QPushButton,QDateEdit,QLabel,QPlainTextEdit,
    QTableWidget,QCheckBox,QMessageBox)

class ConfiguracionTabs(QTabWidget):
    probar_bd = pyqtSignal(dict)
    limpiar_reloj = pyqtSignal()
    registrar_licencia = pyqtSignal()
    extender_licencia = pyqtSignal(str)
    guardar = pyqtSignal()
    def __init__(self,parent=None):
        super().__init__(parent)
        self.reloj={}
        pagina=QWidget();form=QFormLayout(pagina)
        for key,label in [('ip','IP / servidor'),('device_id','ID dispositivo'),('model','Modelo'),('username','Usuario')]:
            field=QLineEdit();self.reloj[key]=field;form.addRow(label,field)
        self.marca=QComboBox();self.marca.addItems(['ZKTeco','Hikvision']);form.addRow('Marca',self.marca)
        self.protocolo=QComboBox();self.protocolo.addItems(['TCP','UDP','HTTP / ISAPI','HTTPS / ISAPI']);form.addRow('Protocolo',self.protocolo)
        self.puerto_reloj=QSpinBox();self.puerto_reloj.setRange(1,65535);self.puerto_reloj.setValue(4370);form.addRow('Puerto',self.puerto_reloj)
        self.clave_reloj=QLineEdit();self.clave_reloj.setEchoMode(QLineEdit.EchoMode.Password);form.addRow('Clave de comunicación / contraseña',self.clave_reloj)
        limpiar=QPushButton('Limpiar buffer del reloj seleccionado')
        limpiar.clicked.connect(lambda checked=False: self.limpiar_reloj.emit())
        form.addRow(limpiar);self.addTab(pagina,'Relojes')
        pagina=QWidget();form=QFormLayout(pagina)
        self.integracion=QCheckBox('Habilitar exportación a un sistema externo');form.addRow(self.integracion)
        self.motor=QComboBox()
        for label,value in [('MySQL / MariaDB','mysql'),('PostgreSQL','postgresql'),('SQL Server','sqlserver'),('Oracle','oracle'),('SQLite','sqlite')]:self.motor.addItem(label,value)
        form.addRow('Motor',self.motor)
        self.bd={}
        for key,label in [('host','Host / servidor'),('database','Base / archivo SQLite'),('username','Usuario'),('password','Contraseña'),('driver_odbc','Driver ODBC'),('service_name','Service Name Oracle')]:
            field=QLineEdit();self.bd[key]=field;form.addRow(label,field)
        self.bd['password'].setEchoMode(QLineEdit.EchoMode.Password)
        self.bd['driver_odbc'].setText('ODBC Driver 18 for SQL Server')
        self.puerto_bd=QSpinBox();self.puerto_bd.setRange(1,65535);form.addRow('Puerto',self.puerto_bd)
        probar=QPushButton('Probar conexión');probar.clicked.connect(self._probar);form.addRow(probar)
        self.motor.currentIndexChanged.connect(self._motor_cambio)
        self._motor_cambio();self.addTab(pagina,'Base externa')
        pagina=QWidget();form=QFormLayout(pagina)
        self.esquema=QComboBox();self.tabla=QComboBox()
        form.addRow('Esquema',self.esquema);form.addRow('Tabla de destino',self.tabla)
        self.fecha_modo=QComboBox();self.fecha_modo.addItems(['Fecha y hora juntas','Fecha y hora separadas']);form.addRow('Formato temporal',self.fecha_modo)
        self.mapeo=QTableWidget(0,3);self.mapeo.setHorizontalHeaderLabels(['Campo de origen','Columna destino','Tipo externo']);form.addRow(self.mapeo)
        self.organizacion=QComboBox();self.organizacion.addItem('Solo Excel / sin organización',None);form.addRow('Organización',self.organizacion)
        self.addTab(pagina,'Mapeo')
        pagina=QWidget();form=QFormLayout(pagina)
        self.estado=QLabel('Sin registrar');self.vencimiento=QLabel('—');self.dias=QLabel('—')
        form.addRow('Estado',self.estado);form.addRow('Vencimiento',self.vencimiento);form.addRow('Días restantes',self.dias)
        registrar=QPushButton('Registrar primera activación (1 año)');registrar.clicked.connect(lambda checked=False: self.registrar_licencia.emit());form.addRow(registrar)
        self.extension=QPlainTextEdit();self.extension.setPlaceholderText('Pegá el código firmado de extensión recibido');form.addRow('Código de extensión',self.extension)
        extender=QPushButton('Aplicar extensión');extender.clicked.connect(lambda:self.extender_licencia.emit(self.extension.toPlainText().strip()));form.addRow(extender)
        self.addTab(pagina,'Licencia')
    def _motor_cambio(self):
        motor=self.motor.currentData()
        self.puerto_bd.setValue({'mysql':3306,'postgresql':5432,'sqlserver':1433,'oracle':1521,'sqlite':1}[motor])
        self.puerto_bd.setEnabled(motor!='sqlite')
        for key in ('host','username','password'):self.bd[key].setEnabled(motor!='sqlite')
        self.bd['driver_odbc'].setEnabled(motor=='sqlserver')
        self.bd['service_name'].setEnabled(motor=='oracle')
    def _probar(self):
        config={key:field.text() for key,field in self.bd.items()}
        config.update(motor=self.motor.currentData(),port=self.puerto_bd.value())
        self.probar_bd.emit(config)
    def confirmar_limpieza(self,nombre,ip,cantidad=None):
        detalle=f'¿Borrar las marcaciones del reloj {nombre} ({ip})?\nNo elimina empleados ni plantillas biométricas.'
        if cantidad is not None:detalle+=f'\nMarcaciones informadas por el dispositivo: {cantidad}.'
        return QMessageBox.question(self,'Confirmar limpieza',detalle,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes

class FiltrosMarcaciones(QWidget):
    consultar = pyqtSignal(dict)
    def __init__(self,parent=None):
        super().__init__(parent)
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
        self.desde.setEnabled(custom);self.hasta.setEnabled(custom)
        self.tarjeta.setEnabled(self.modo.currentIndex()==2)
    def _consultar(self):
        self.consultar.emit({'origen':self.origen.currentIndex(),'modo':self.modo.currentIndex(),
                             'desde':self.desde.date().toPyDate(),'hasta':self.hasta.date().toPyDate(),
                             'tarjeta':self.tarjeta.text().strip() if self.modo.currentIndex()==2 else None})
