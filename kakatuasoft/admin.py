from django import forms
from django.contrib import admin
from .models import Usuario, Estacao, Configuracao


@admin.register(Usuario)
class UsuarioAdmin(admin.ModelAdmin):
    list_display = ('Login',)


@admin.register(Estacao)
class EstacaoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'ocupada_por', 'ocupada_em')


class ConfiguracaoForm(forms.ModelForm):
    class Meta:
        model = Configuracao
        fields = '__all__'
        widgets = {
            'email_senha_app': forms.PasswordInput(render_value=True),
            'api_key': forms.PasswordInput(render_value=True),
        }


@admin.register(Configuracao)
class ConfiguracaoAdmin(admin.ModelAdmin):
    form = ConfiguracaoForm

    def has_add_permission(self, request):
        return not Configuracao.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
