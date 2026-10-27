

from django.shortcuts import render, redirect
from django.contrib import messages
from .models import Usuario, Estacao
from django.http import JsonResponse
from .servidor import enviar_acesso, consultar_estacao, consultar_tranca, enviar_comando
from django.conf import settings
from functools import wraps
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.core import signing
from django.core.mail import send_mail
from django.urls import reverse
from .limpeza import limpar_nao_confirmados
import math

# pks das estações que já têm sensor (as outras ainda não têm)
ESTACOES_COM_SENSOR = {1, 2}

# valores do campo "estado" da API que significam "sensor detectando algo"
# valor que o ESP manda quando o sensor detecta algo
ESTADOS_DETECTANDO = {'fechada'}

DOMINIO_PERMITIDO = 'unisantos.br'

SALT_VERIFICACAO = 'verificar-email'
VALIDADE_LINK = 60 * 60 * 24   # 24 horas

TIMEOUT_REOCUPAR = 60

RAIO_PERMITIDO_M = 100        # distância máxima até a estação
PRECISAO_MAXIMA_M = 150       # recusa localização muito imprecisa
EXIGIR_LOCALIZACAO = True     # False para testar fora do local


def fazer_login(request):
    if request.method == 'POST':
        login_usuario = request.POST.get('Login')
        senha = request.POST.get('Senha')

        try:
            usuario = Usuario.objects.get(Login=login_usuario)
            if usuario.check_senha(senha):
                if usuario.Email and not usuario.email_verificado:
                    _enviar_verificacao(request, usuario)   # reenvia o link
                    return render(request, 'page1.html', {
                        'erro': 'Confirme seu e-mail antes de entrar. Enviamos um novo link para você.'})
                request.session['usuario_id'] = usuario.id

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
        'exigir_localizacao': EXIGIR_LOCALIZACAO,
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


def _distancia_m(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def _perto_da_estacao(request, estacao):
    """Retorna (ok, mensagem)."""
    if not EXIGIR_LOCALIZACAO or estacao.latitude is None or estacao.longitude is None:
        return True, ''   # estação sem coordenadas não exige localização
    try:
        lat = float(request.POST['lat'])
        lon = float(request.POST['lon'])
        precisao = float(request.POST.get('precisao', 0))
    except (KeyError, ValueError):
        return False, 'Não foi possível obter sua localização. Permita o acesso e tente de novo.'
    if precisao > PRECISAO_MAXIMA_M:
        return False, 'Localização imprecisa. Ative o GPS e tente de novo.'
    dist = _distancia_m(lat, lon, estacao.latitude, estacao.longitude)
    if dist > RAIO_PERMITIDO_M:
        return False, f'Você precisa estar perto da estação (distância: {int(dist)} m).'
    return True, ''


@login_necessario
@require_POST
def ocupar_estacao(request, pk):
    restante = _segundos_restantes(request.usuario)
    if restante > 0:
        messages.error(
            request, f'Aguarde {restante} s para guardar a bike novamente.')
        return redirect('page2')
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
            ok, aviso = _perto_da_estacao(request, estacao)
            if not ok:
                messages.error(request, aviso)
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
        usuario = Usuario.objects.select_for_update().get(pk=request.usuario.pk)
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
            usuario.ultima_liberacao = timezone.now()
            usuario.save(update_fields=['ultima_liberacao'])
            messages.success(request, 'Estação liberada.')
    return redirect('page2')


def _segundos_restantes(usuario):
    if not usuario.ultima_liberacao:
        return 0
    passou = (timezone.now() - usuario.ultima_liberacao).total_seconds()
    return max(0, math.ceil(TIMEOUT_REOCUPAR - passou))


def cadastro(request):
    if request.method == 'POST':
        limpar_nao_confirmados()

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

        if _enviar_verificacao(request, usuario):
            messages.success(
                request, 'Conta criada! Enviamos um link de confirmação para o seu e-mail.')
        else:
            messages.error(
                request, 'Conta criada, mas não foi possível enviar o e-mail. Tente entrar para receber um novo link.')
        return redirect('page1')

    return render(request, 'cadastro.html')


def _email_institucional(email):
    """True se for um e-mail válido do domínio permitido."""
    try:
        validate_email(email)
    except ValidationError:
        return False
    return email.rpartition('@')[2] == DOMINIO_PERMITIDO


def _enviar_verificacao(request, usuario):
    token = signing.dumps(
        {'uid': usuario.pk, 'email': usuario.Email}, salt=SALT_VERIFICACAO)
    link = request.build_absolute_uri(reverse('verificar_email', args=[token]))
    if settings.DEBUG:   # só aparece em teste
        print(f'\n>>> LINK DE VERIFICAÇÃO: {link}\n')
    try:
        send_mail(
            subject='Confirme seu e-mail - Kakatua Bikes',
            message=(f'Olá, {usuario.Login}!\n\n'
                     f'Confirme seu e-mail para ativar sua conta:\n{link}\n\n'
                     'O link vale por 24 horas.'),
            from_email=None,   # usa DEFAULT_FROM_EMAIL
            recipient_list=[usuario.Email],
        )
        return True
    except Exception as e:
        print(f'Erro ao enviar e-mail de verificação: {e}')
        return False


def verificar_email(request, token):
    try:
        dados = signing.loads(
            token, salt=SALT_VERIFICACAO, max_age=VALIDADE_LINK)
    except signing.SignatureExpired:
        messages.error(
            request, 'Link expirado. Tente entrar para receber um novo.')
        return redirect('page1')
    except signing.BadSignature:
        messages.error(request, 'Link inválido.')
        return redirect('page1')

    try:
        usuario = Usuario.objects.get(pk=dados['uid'], Email=dados['email'])
    except Usuario.DoesNotExist:
        messages.error(request, 'Conta não encontrada.')
        return redirect('page1')

    usuario.email_verificado = True
    usuario.save()
    messages.success(request, 'E-mail confirmado! Agora você já pode entrar.')
    return redirect('page1')


def logout_view(request):
    request.session.flush()
    return redirect('page1')
