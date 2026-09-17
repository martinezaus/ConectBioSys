"""Tabla virtual: no crea miles de widgets al mostrar marcaciones."""
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

class ModeloMarcaciones(QAbstractTableModel):
    def __init__(self, filas, encabezados, parent=None):
        super().__init__(parent)
        self.filas = filas
        self.encabezados = ['', *encabezados]
        self.todos = True
        self.excepciones = set()
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.filas)
    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.encabezados)
    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid(): return None
        if index.column() == 0 and role == Qt.CheckStateRole:
            return Qt.Checked if self.marcada(index.row()) else Qt.Unchecked
        if index.column() > 0 and role == Qt.DisplayRole:
            return str(self.filas[index.row()][index.column()-1])
        return None
    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            return self.encabezados[section] if orientation == Qt.Horizontal else section + 1
        return None
    def flags(self, index):
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        return flags | Qt.ItemIsUserCheckable if index.column() == 0 else flags
    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid() or index.column() != 0 or role != Qt.CheckStateRole: return False
        checked = value in (Qt.Checked, Qt.Checked.value)
        if checked == self.todos: self.excepciones.discard(index.row())
        else: self.excepciones.add(index.row())
        self.dataChanged.emit(index, index, [Qt.CheckStateRole])
        return True
    def marcada(self, row):
        return self.todos != (row in self.excepciones)
    def marcar_todas(self, estado):
        self.todos = bool(estado)
        self.excepciones.clear()
        if self.filas: self.dataChanged.emit(self.index(0,0), self.index(len(self.filas)-1,0), [Qt.CheckStateRole])
    def seleccionadas(self):
        return [fila for i, fila in enumerate(self.filas) if self.marcada(i)]
