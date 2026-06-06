# KakatuaSoftware

Site e API do sistema de bicicletário Kakatua Bikes, desenvolvido com Django.

## Tecnologias

- Python / Django
- Django REST Framework
- MySQL
- Nginx (proxy reverso)
- HTML / CSS

## Como rodar

```bash
pip install -r requirements.txt
python manage.py runserver
```

## Endpoints

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| POST | `/api/sensor/estacao/` | Atualiza o status da estação |
| POST | `/api/sensor/acesso/` | Atualiza o estado de uma tranca |
