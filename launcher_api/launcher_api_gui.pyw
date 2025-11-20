# -*- coding: utf-8 -*-
# Ensure the launcher GUI actually starts when run with pythonw
from launcher_api_gui import Launcher

if __name__ == "__main__":
    Launcher().mainloop()
