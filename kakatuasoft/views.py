from django.shortcuts import render, redirect
from django.contrib import messages
from .models import Usuario, estacao
from .servidor import enviar_acesso, consultar_estacao


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


def station():
    return 1 if consultar_estacao() else 0


def page2(request):
    usuario_id = request.session.get('usuario_id')
    if not usuario_id:
        return redirect('page1')

    try:
        usuario = Usuario.objects.get(id=usuario_id)
        return render(request, 'page2.html', {
            'usuario': usuario,
            'status_estacao': station()
        })
    except Usuario.DoesNotExist:
        return redirect('page1')


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

        messages.success(request, 'Cadastro realizado com sucesso! Faça login.')
        return redirect('page1')

    return render(request, 'cadastro.html')


def logout_view(request):
    request.session.flush()
    return redirect('page1')