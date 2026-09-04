"""Entry point for the ball-balancer control application."""
from __future__ import annotations

import sys

from PyQt5.QtWidgets import QApplication

from gui import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Ball Balancer")
    window = MainWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
