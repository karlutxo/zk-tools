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
