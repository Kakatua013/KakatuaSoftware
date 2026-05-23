
from django.db import models

# Importa funções para criptografar e verificar senhas de forma segura
from django.contrib.auth.hashers import make_password, check_password


class Usuario(models.Model):
    Login = models.CharField(max_length=50, unique=True)
    Senha = models.CharField(max_length=128)

    id_tranca = models.IntegerField(default=0)
    estado_tranca = models.IntegerField(default=0)
    tranca_reservada = models.IntegerField(default=0)

    # Método para definir/alterar a senha do usuário de forma segura
    # Recebe a senha em texto puro (senha_raw) como parâmetro
    def set_senha(self, senha_raw):
        # make_password() criptografa a senha texto puro para um HASH seguro
        # O HASH gerado é uma string de 128 caracteres que representa a senha
        # Atribui este HASH ao campo Senha do objeto
        self.Senha = make_password(senha_raw)
        # OBSERVAÇÃO: Este método apenas altera o atributo, não salva no banco
        # Você precisa chamar .save() depois para persistir no banco

    # Método para verificar se uma senha fornecida corresponde à senha do usuário
    # Recebe uma senha em texto puro (senha_raw) como parâmetro
    # Retorna True se a senha estiver correta, False caso contrário
    def check_senha(self, senha_raw):
        # check_password() compara a senha texto puro com o HASH armazenado
        # Ela aplica a mesma criptografia na senha fornecida e compara com o HASH
        # Retorna True se coincidirem, False se forem diferentes
        return check_password(senha_raw, self.Senha)

    # Quando você der print em um objeto Usuario, ou vê-lo no admin Django
    # Ele retornará o valor do campo Login em vez de "Objeto Usuario (123)"

    def __str__(self):
        return self.Login


#  NO TERMINAL, FAÇA ISSO PARA SALVAR USUARIO E SENHA (nome e senha usado são exemplos)
#      python manage.py shell

#      >>> from kakatuasoft.models import Usuario
#      >>> usuario = Usuario(Login='Gusta')
#      >>> usuario.set_senha('teste_123')
#      >>> usuario.save()

class estacao(models.Model):

    def verifica_station(self):
        return 1
