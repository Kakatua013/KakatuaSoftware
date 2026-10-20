

from django.shortcuts import render, redirect
from django.contrib import messages
from .models import Usuario, Estacao
from django.http import JsonResponse
from .servidor import enviar_acesso, consultar_estacao, consultar_tranca, enviar_comando
from functools import wraps
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.core.exceptions import ValidationError
from django.core.validators import validate_email


# pks das estações que já têm sensor (as outras ainda não têm)
ESTACOES_COM_SENSOR = {1, 2}

# valores do campo "estado" da API que significam "sensor detectando algo"
# valor que o ESP manda quando o sensor detecta algo
ESTADOS_DETECTANDO = {'fechada'}

DOMINIO_PERMITIDO = 'unisantos.br'


def fazer_login(request):
    if request.method == 'POST':
        login_usuario = request.POST.get('Login')
        senha = request.POST.get('Senha')

        try:
            usuario = Usuario.objects.get(Login=login_usuario)
            if usuario.check_senha(senha):
                request.session['usuario_id'] = usuario.id
                request.session['usuario_login'] = usuario.Login

                enviar_acesso(usuario)  # ← envia login pro servidor

                return redirect('page2')
            else:
                return render(request, 'page1.html', {'erro': 'Senha inválida'})
        except Usuario.DoesNotExist:
            return render(request, 'page1.html', {'erro': 'Usuário não encontrado'})

    return render(request, 'page1.html')


def login_necessario(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        usuario_id = request.session.get('usuario_id')
        if not usuario_id:
            return redirect('page1')
        try:
            request.usuario = Usuario.objects.get(id=usuario_id)
        except Usuario.DoesNotExist:
            request.session.flush()
            return redirect('page1')
        return view(request, *args, **kwargs)
    return wrapper


@login_necessario
def estado_json(request):
    return JsonResponse(_estado_servidor(Estacao.objects.all().order_by('id')))


@login_necessario
def page2(request):
    estacoes = list(Estacao.objects.all().order_by('id'))
    estado = _estado_servidor(estacoes)
    for e in estacoes:
        e.tranca = estado['trancas'].get(e.pk)
        e.sensor_bloqueia = estado['sensor_bloqueia'][e.pk]
    return render(request, 'page2.html', {
        'usuario': request.usuario,
        'estacoes': estacoes,
        'bloqueada': estado['bloqueada'],
    })


def _sensor_bloqueia(pk, tranca):
    """True se a estação tem sensor e ele está detectando algo
    (ou se não deu para verificar)."""
    if pk not in ESTACOES_COM_SENSOR:
        return False
    if tranca is None:
        return True
    return str(tranca.get('estado')).strip().lower() in ESTADOS_DETECTANDO


def _estado_servidor(estacoes):
    bloqueada = consultar_estacao()
    if bloqueada is None:  # servidor indisponível
        return {
            'bloqueada': None,
            'trancas': {},
            'sensor_bloqueia': {e.pk: _sensor_bloqueia(e.pk, None) for e in estacoes},
        }
    trancas = {
        e.pk: consultar_tranca(e.pk) if e.pk in ESTACOES_COM_SENSOR else None
        for e in estacoes
    }
    return {
        'bloqueada': bloqueada,
        'trancas': trancas,
        'sensor_bloqueia': {e.pk: _sensor_bloqueia(e.pk, trancas[e.pk]) for e in estacoes},
    }


@login_necessario
@require_POST
def ocupar_estacao(request, pk):
    if pk in ESTACOES_COM_SENSOR:
        tranca = consultar_tranca(pk)
        if _sensor_bloqueia(pk, tranca):
            if tranca is None:
                messages.error(
                    request, 'Não foi possível verificar o sensor. Tente novamente.')
            else:
                messages.error(
                    request, 'O sensor está detectando algo. Aguarde para armazenar.')
            return redirect('page2')

    with transaction.atomic():
        # trava a linha no banco: evita dois usuários pegarem a mesma estação ao mesmo tempo
        estacao = get_object_or_404(Estacao.objects.select_for_update(), pk=pk)

        if not estacao.livre:
            messages.error(request, 'Esta estação já está ocupada.')
        else:
            if request.usuario.estacoes_ocupadas.exists():
                messages.error(
                    request, 'Você já está com uma estação ocupada.')
                return redirect('page2')

            # NOVO: manda a tranca fechar (só estações com sensor/solenoide)
            if pk in ESTACOES_COM_SENSOR and not enviar_comando(pk, 'fechar'):
                messages.error(
                    request, 'Não foi possível acionar a tranca. Tente novamente.')
                return redirect('page2')

            estacao.ocupada_por = request.usuario
            estacao.ocupada_em = timezone.now()
            estacao.save()
            messages.success(request, 'Estação ocupada com sucesso.')
    return redirect('page2')


@login_necessario
@require_POST
def liberar_estacao(request, pk):
    with transaction.atomic():
        Usuario.objects.select_for_update().get(pk=request.usuario.pk)
        estacao = get_object_or_404(Estacao.objects.select_for_update(), pk=pk)

        # regra principal: só quem ocupou pode liberar
        if estacao.ocupada_por_id != request.usuario.id:
            messages.error(request, 'Só quem ocupou a estação pode liberá-la.')
        # NOVO: manda a tranca abrir antes de liberar no banco
        elif pk in ESTACOES_COM_SENSOR and not enviar_comando(pk, 'abrir'):
            messages.error(
                request, 'Não foi possível acionar a tranca. Tente novamente.')
        else:
            estacao.ocupada_por = None
            estacao.ocupada_em = None
            estacao.save()
            messages.success(request, 'Estação liberada.')
    return redirect('page2')


def cadastro(request):
    if request.method == 'POST':
        login_usuario = request.POST.get('Login')
        email = request.POST.get('Email', '').strip().lower()
        senha = request.POST.get('Senha')
        confirmar_senha = request.POST.get('ConfirmarSenha')

        if not _email_institucional(email):
            return render(request, 'cadastro.html', {'erro': 'Use seu e-mail institucional @unisantos.br'})

        if senha != confirmar_senha:
            return render(request, 'cadastro.html', {'erro': 'As senhas não coincidem'})

        if Usuario.objects.filter(Login=login_usuario).exists():
            return render(request, 'cadastro.html', {'erro': 'Login já existe'})

        if Usuario.objects.filter(Email=email).exists():
            return render(request, 'cadastro.html', {'erro': 'Este e-mail já está cadastrado'})

        usuario = Usuario(Login=login_usuario, Email=email)
        usuario.set_senha(senha)
        usuario.save()

        enviar_acesso(usuario)  # ← envia cadastro pro servidor

        messages.success(
            request, 'Cadastro realizado com sucesso! Faça login.')
        return redirect('page1')

    return render(request, 'cadastro.html')


def _email_institucional(email):
    """True se for um e-mail válido do domínio permitido."""
    try:
        validate_email(email)
    except ValidationError:
        return False
    return email.rpartition('@')[2] == DOMINIO_PERMITIDO


def logout_view(request):
    request.session.flush()
    return redirect('page1')
