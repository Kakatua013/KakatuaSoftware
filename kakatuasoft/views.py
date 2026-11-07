from django.shortcuts import render, redirect
from django.contrib import messages
from .models import Usuario, Estacao
from .config import obter
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
import json
import re
import hmac
from datetime import timedelta
from django.views.decorators.csrf import csrf_exempt

# pks das estações que já têm sensor (as outras ainda não têm)
ESTACOES_COM_SENSOR = {1, 2}

# valores do campo "estado" da API que significam "sensor detectando algo"
# valor que o ESP manda quando o sensor detecta algo
ESTADOS_DETECTANDO = {'fechada'}

DOMINIO_PERMITIDO = 'unisantos.br'

SALT_VERIFICACAO = 'verificar-email'
VALIDADE_LINK = 60 * 60 * 24   # 24 horas

TIMEOUT_REOCUPAR = 10

JANELA_CADASTRO_TAG = 60     # segundos para o usuário aproximar a tag do leitor

RAIO_PERMITIDO_M = 200       # distância máxima até a estação
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
    estacoes = list(Estacao.objects.all().order_by('id'))
    dados = _estado_servidor(estacoes)
    dados['situacoes'] = {e.pk: _situacao(
        e, request.usuario) for e in estacoes}
    return JsonResponse(dados)


def _situacao(estacao, usuario):
    if estacao.livre:
        return 'livre'
    return 'sua' if estacao.ocupada_por_id == usuario.pk else 'ocupada'


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
        'tem_tag': bool(request.usuario.tag_uid),
        'tag_aguardando': _segundos_cadastro_tag(request.usuario),
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


def _ocupar(usuario, pk):
    """Regras de 'guardar a bike' (a checagem de localização é feita antes, nas telas
    que têm GPS). Usada pelo site e pelo leitor de tag. Retorna (ok, mensagem)."""
    restante = _segundos_restantes(usuario)
    if restante > 0:
        return False, f'Aguarde {restante} s para guardar a bike novamente.'
    if pk in ESTACOES_COM_SENSOR:
        tranca = consultar_tranca(pk)
        if _sensor_bloqueia(pk, tranca):
            if tranca is None:
                return False, 'Não foi possível verificar o sensor. Tente novamente.'
            return False, 'O sensor está detectando algo. Aguarde para armazenar.'

    with transaction.atomic():
        # trava a linha no banco: evita dois usuários pegarem a mesma estação ao mesmo tempo
        estacao = Estacao.objects.select_for_update().filter(pk=pk).first()
        if estacao is None:
            return False, 'Estação não encontrada.'
        if not estacao.livre:
            return False, 'Esta estação já está ocupada.'
        if usuario.estacoes_ocupadas.exists():
            return False, 'Você já está com uma estação ocupada.'
        # manda a tranca fechar (só estações com sensor/solenoide)
        if pk in ESTACOES_COM_SENSOR and not enviar_comando(pk, 'fechar'):
            return False, 'Não foi possível acionar a tranca. Tente novamente.'
        estacao.ocupada_por = usuario
        estacao.ocupada_em = timezone.now()
        estacao.save()
    return True, 'Estação ocupada com sucesso.'


def _liberar(usuario, pk):
    """Regras de 'liberar a estação' (retirar a bike). Retorna (ok, mensagem)."""
    with transaction.atomic():
        dono = Usuario.objects.select_for_update().get(pk=usuario.pk)
        estacao = Estacao.objects.select_for_update().filter(pk=pk).first()
        if estacao is None:
            return False, 'Estação não encontrada.'
        # regra principal: só quem ocupou pode liberar
        if estacao.ocupada_por_id != dono.pk:
            return False, 'Só quem ocupou a estação pode liberá-la.'
        # manda a tranca abrir antes de liberar no banco
        if pk in ESTACOES_COM_SENSOR and not enviar_comando(pk, 'abrir'):
            return False, 'Não foi possível acionar a tranca. Tente novamente.'
        estacao.ocupada_por = None
        estacao.ocupada_em = None
        estacao.save()
        dono.ultima_liberacao = timezone.now()
        dono.save(update_fields=['ultima_liberacao'])
    return True, 'Estação liberada.'


@login_necessario
@require_POST
def ocupar_estacao(request, pk):
    estacao = get_object_or_404(Estacao, pk=pk)
    ok, aviso = _perto_da_estacao(request, estacao)
    if not ok:
        messages.error(request, aviso)
        return redirect('page2')
    ok, texto = _ocupar(request.usuario, pk)
    if ok:
        messages.success(request, texto)
    else:
        messages.error(request, texto)
    return redirect('page2')


@login_necessario
@require_POST
def liberar_estacao(request, pk):
    ok, texto = _liberar(request.usuario, pk)
    if ok:
        messages.success(request, texto)
    else:
        messages.error(request, texto)
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
        # e-mail e senha de app: variáveis de ambiente ou, se não houver, o /admin
        email_usuario = obter('EMAIL_USER', 'email_usuario')
        senha_app = obter('EMAIL_SENHA_APP', 'email_senha_app')
        send_mail(
            subject='Confirme seu e-mail - Kakatua Bikes',
            message=(f'Olá, {usuario.Login}!\n\n'
                     f'Confirme seu e-mail para ativar sua conta:\n{link}\n\n'
                     'O link vale por 24 horas.'),
            from_email=f'Kakatua Bikes <{email_usuario}>',
            recipient_list=[usuario.Email],
            auth_user=email_usuario,
            auth_password=senha_app,
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


# ───────────────────────── Tag RFID/NFC ─────────────────────────

def _segundos_cadastro_tag(usuario):
    """Segundos que ainda restam para o usuário aproximar a tag do leitor (0 = não está cadastrando)."""
    if not usuario.cadastrando_tag_ate:
        return 0
    return max(0, math.ceil((usuario.cadastrando_tag_ate - timezone.now()).total_seconds()))


def _estado_tag(usuario):
    return {
        'tem_tag': bool(usuario.tag_uid),
        'aguardando': _segundos_cadastro_tag(usuario),
        'cadastrada_em': int(usuario.tag_cadastrada_em.timestamp()) if usuario.tag_cadastrada_em else 0,
    }


def _perto_de_alguma_estacao(request):
    """O leitor fica nas estações: exige estar perto de ao menos uma que tenha coordenadas."""
    com_coordenadas = [e for e in Estacao.objects.all()
                       if e.latitude is not None and e.longitude is not None]
    if not EXIGIR_LOCALIZACAO or not com_coordenadas:
        return True, ''
    aviso = ''
    for e in com_coordenadas:
        ok, aviso = _perto_da_estacao(request, e)
        if ok:
            return True, ''
    return False, aviso


@login_necessario
@require_POST
def cadastrar_tag(request):
    """Abre a janela em que a próxima tag lida no leitor vira a tag deste usuário."""
    ok, aviso = _perto_de_alguma_estacao(request)
    if not ok:
        messages.error(request, aviso)
        return redirect('page2')

    agora = timezone.now()
    outro = Usuario.objects.filter(
        cadastrando_tag_ate__gt=agora).exclude(pk=request.usuario.pk).exists()
    if outro:
        messages.error(
            request, 'Outra pessoa está cadastrando uma tag agora. Tente de novo em instantes.')
        return redirect('page2')

    request.usuario.cadastrando_tag_ate = agora + \
        timedelta(seconds=JANELA_CADASTRO_TAG)
    request.usuario.save(update_fields=['cadastrando_tag_ate'])
    messages.success(
        request, f'Aproxime a tag do leitor da estação em até {JANELA_CADASTRO_TAG} s.')
    return redirect('page2')


@login_necessario
def tag_status(request):
    return JsonResponse(_estado_tag(request.usuario))


def _processar_tag(uid, id_tranca):
    """Decide o que fazer com uma tag lida no leitor. Retorna (resultado, mensagem)."""
    agora = timezone.now()

    # 1) alguém está cadastrando uma tag? Então esta leitura é o cadastro dele.
    pendente = Usuario.objects.filter(
        cadastrando_tag_ate__gt=agora).order_by('cadastrando_tag_ate').first()
    if pendente:
        if Usuario.objects.filter(tag_uid=uid).exclude(pk=pendente.pk).exists():
            return 'recusada', 'Esta tag ja esta cadastrada em outra conta.'
        pendente.tag_uid = uid
        pendente.tag_cadastrada_em = agora
        pendente.cadastrando_tag_ate = None
        pendente.save(
            update_fields=['tag_uid', 'tag_cadastrada_em', 'cadastrando_tag_ate'])
        return 'cadastrada', f'Tag cadastrada para {pendente.Login}.'

    # 2) uso normal: guarda ou libera a estação do dono da tag
    usuario = Usuario.objects.filter(tag_uid=uid).first()
    if usuario is None:
        return 'desconhecida', 'Tag nao cadastrada.'

    ocupada = usuario.estacoes_ocupadas.first()
    if ocupada:
        # a tag libera a estação que o usuário já está usando
        if id_tranca and ocupada.pk != id_tranca:
            return 'recusada', f'Sua bike esta na estacao {ocupada.pk}.'
        ok, texto = _liberar(usuario, ocupada.pk)
        return ('liberada' if ok else 'recusada'), texto

    # sem estação ocupada: a tag guarda a bike. Leitor único (id 0): tenta as estações com sensor em ordem.
    candidatas = [id_tranca] if id_tranca else sorted(ESTACOES_COM_SENSOR)
    texto = 'Nenhuma estacao disponivel.'
    for pk in candidatas:
        ok, texto = _ocupar(usuario, pk)
        if ok:
            return 'guardada', texto
    return 'recusada', texto


@csrf_exempt
@require_POST
def tag_lida(request):
    """Chamado pelo ESP32 quando o leitor lê uma tag. Protegido pela mesma API key do ESP."""
    chave = obter('API_KEY', 'api_key')
    enviada = request.headers.get('X-API-Key', '')
    if not chave or not hmac.compare_digest(enviada.encode(), chave.encode()):
        return JsonResponse({'resultado': 'nao_autorizado', 'mensagem': 'API key invalida.'}, status=401)
    try:
        dados = json.loads(request.body)
        uid = str(dados['uid']).strip().upper()
        id_tranca = int(dados.get('id_tranca') or 0)
    except (ValueError, KeyError, TypeError):
        return JsonResponse({'resultado': 'invalido', 'mensagem': 'Requisicao invalida.'}, status=400)
    if not re.fullmatch(r'[0-9A-F]{4,20}', uid):
        return JsonResponse({'resultado': 'invalido', 'mensagem': 'UID invalido.'}, status=400)

    resultado, mensagem = _processar_tag(uid, id_tranca)
    print(f'[TAG] {uid} -> {resultado}: {mensagem}')
    return JsonResponse({'resultado': resultado, 'mensagem': mensagem})
