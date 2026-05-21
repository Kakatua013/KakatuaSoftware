# kakatua/views.py
from django.shortcuts import render, redirect
from django.contrib import messages
from .models import Usuario, estacao



def fazer_login(request):
    if request.method == 'POST':
        login_usuario = request.POST.get('Login')
        senha = request.POST.get('Senha')

        try:
            usuario = Usuario.objects.get(Login=login_usuario)
            if usuario.check_senha(senha):
                # Salva o ID na sessão
                request.session['usuario_id'] = usuario.id
                request.session['usuario_login'] = usuario.Login

                print(f"Login bem-sucedido: {usuario.Login}")
                return redirect('page2')  # Redireciona para page2
            else:
                print("Senha inválida")
                return render(request, 'page1.html', {'erro': 'Senha inválida'})
        except Usuario.DoesNotExist:
            print("Usuário não encontrado")
            return render(request, 'page1.html', {'erro': 'Usuário não encontrado'})

    return render(request, 'page1.html')

def station():
    verifica_station = estacao() # classe dentro da modles.py
    valor = verifica_station.verifica_station() #função dentro da classe de modles.py
    return valor


def page2(request):
    # Verifica se o usuário está logado
    usuario_id = request.session.get('usuario_id')
    if not usuario_id:
        print("Usuário não logado, redirecionando para page1")
        return redirect('page1')

    try:
        usuario = Usuario.objects.get(id=usuario_id)
        # Chama a sua função station e guarda o resultado (0 ou 1)

        # Passamos o 'status' para o HTML dentro do dicionário de contexto
        return render(request, 'page2.html', {
            'usuario': usuario, 
            'status_estacao': station()  # Agora o HTML conhece esse valor
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
        messages.success(request, 'Cadastro realizado com sucesso! Faça login.')
        return redirect('page1')
    return render(request, 'cadastro.html')

def logout_view(request):
    # Remove os dados da sessão
    request.session.flush()  # Limpa toda a sessão
    # Se preferir remover apenas os dados específicos:
    # request.session.pop('usuario_id', None)
    # request.session.pop('usuario_login', None)
    
    return redirect('page1')
