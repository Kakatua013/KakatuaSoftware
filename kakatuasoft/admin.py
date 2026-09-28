from django.contrib import admin
from .models import Usuario, Estacao


@admin.register(Usuario)
class UsuarioAdmin(admin.ModelAdmin):
    list_display = ('Login',)


@admin.register(Estacao)
class EstacaoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'ocupada_por', 'ocupada_em')