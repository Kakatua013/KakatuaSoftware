from django.shortcuts import render, redirect
from django.contrib import messages
from .models import Usuario, Estacao
from .servidor import enviar_acesso, consultar_estacao
from functools import wraps
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.views.decorators.http import require_POST


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
def page2(request):
    estacoes = Estacao.objects.all().order_by('id')
    return render(request, 'page2.html', {
        'usuario': request.usuario,
        'estacoes': estacoes,
    })


@login_necessario
@require_POST
def ocupar_estacao(request, pk):
    with transaction.atomic():
        # trava a linha no banco: evita dois usuários pegarem a mesma estação ao mesmo tempo
        estacao = get_object_or_404(Estacao.objects.select_for_update(), pk=pk)

        if not estacao.livre:
            messages.error(request, 'Esta estação já está ocupada.')
        else:
            if request.usuario.estacoes_ocupadas.exists():
                messages.error(request, 'Você já está com uma estação ocupada.')
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
        estacao = get_object_or_404(Estacao.objects.select_for_update(), pk=pk)

        # regra principal: só quem ocupou pode liberar
        if estacao.ocupada_por_id != request.usuario.id:
            messages.error(request, 'Só quem ocupou a estação pode liberá-la.')
        else:
            estacao.ocupada_por = None
            estacao.ocupada_em = None
            estacao.save()
            messages.success(request, 'Estação liberada.')
    return redirect('page2')


def cadastro(request):
    if request.method == 'POST':
        login_usuario = request.POST.get('Login')
        senha = request.POST.get('Senha')
        confirmar_senha = request.POST.get('ConfirmarSenha')

        if senha != confirmar_senha:
            return render(request, 'cadastro.html', {'erro': 'As senhas não coincidem'})

        if Usuario.objects.filter(Login=login_usuario).exists():
            return render(request, 'cadastro.html', {'erro': 'Login já existe'})

        usuario = Usuario(Login=login_usuario)
        usuario.set_senha(senha)
        usuario.save()

        enviar_acesso(usuario)  # ← envia cadastro pro servidor

        messages.success(
            request, 'Cadastro realizado com sucesso! Faça login.')
        return redirect('page1')

    return render(request, 'cadastro.html')


def logout_view(request):
    request.session.flush()
    return redirect('page1')
