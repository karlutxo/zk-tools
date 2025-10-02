python3 -m venv .venv

source .venv/bin/activate
pip install -r requirements.txt



python zk_tools.py --help
### Lista empleados del terminal. Todos o solo los que tienen tarjeta registrada ###
python zk_tools_py.py 192.9.210.91 --list-users
python zk_tools.py 192.9.210.91 --list-users --solo-tarjeta

### Sincroniza tarjeta entre terminales. En este caso de 121.212 a 121.214. ###
python sync_cards.py 192.9.121.212 192.9.121.214

### Fecha y Hora de los terminales  ###
# Obtiene fecha y hora del terminal.
python zk_tools_py.py 192.9.210.91 --set-time 
# Establece fecha y hora del terminal según la hora del sistema.
python zk_tools_py.py 192.9.210.91 --sync-time 


### Otras Utilidades ###
python zk_tools_py.py 192.9.210.91 --voice-test
python zk_tools_py.py 192.9.210.91 --disable --list-users --enable

### Documentación ###
https://pyzk.readthedocs.io/en/stable/

## Servidor web con Flask

El proyecto incluye un servidor sencillo (`app.py`) que permite consultar la lista de empleados registrados en un terminal ZKTeco, mostrar su número de tarjeta y los datos biométricos disponibles, y seleccionar uno o varios empleados para usos posteriores.

La tabla de resultados admite seleccionar todos los empleados, filtrar por texto y ejecutar acciones sobre la selección actual:

- Guardar los UID seleccionados en memoria durante la sesión.
- Eliminar del terminal a los empleados seleccionados.
- Exportar los registros seleccionados a CSV, JSON o Excel (`.xlsx`).

### Ejecución

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

La aplicación se expone en `http://localhost:5000`. Desde allí se puede introducir la dirección IP (y opcionalmente el puerto) del terminal a consultar. Los empleados recuperados se muestran en una tabla con casillas de selección; la selección realizada se mantiene en memoria mientras la aplicación esté en ejecución y puede exportarse en los formatos disponibles o eliminarse del terminal.
