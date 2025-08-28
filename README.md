source venv/bin/activate
pip install -r requirements.txt


python zk_tools_py27.py 192.9.210.91 --list-users
python zk_tools_py27.py 192.9.210.91 --voice-test
python zk_tools_py27.py 192.9.210.91 --disable --list-users --enable

