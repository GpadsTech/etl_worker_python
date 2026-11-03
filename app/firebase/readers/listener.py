"""
Escuta novos registros
no Firebase
"""

from app.firebase.client import FirebaseClient


class Listener:

    def __init__(self):

        self.client = FirebaseClient()

    def start(self):

        print(
            "Listener iniciado. "
            "Implementação será concluída na próxima etapa."
        )