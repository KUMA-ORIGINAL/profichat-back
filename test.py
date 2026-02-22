import requests

# Логин для доступа к платформе smspro.nikita.kg.
login = 'qitep'
# Пароль для доступа к платформе smspro.nikita.kg.
password = 'RgAw6Mt4'
# ID транзакции, который использовался при отправке СМС.
transactionId = 'd438875399'

xml_data = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<dr>
    <login>{login}</login>
    <pwd>{password}</pwd>
    <id>{transactionId}</id>
</dr>"""


# Если отправка производилась сразу по нескольким телефонам, то можно запросить отчет для одного конкретного телефона.
# phone = '996550403993'
# xml_data = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
# <dr>
#    <login>{login}</login>
#    <pwd>{password}</pwd>
#    <id>{transactionId}</id>
#    <phone>{phone}</phone>
#</dr>"""


url = 'https://smspro.nikita.kg/api/dr'
headers = {'Content-Type': 'application/xml'}

response = requests.post(url, data=xml_data, headers=headers)
if response.status_code == 200:
    print('Ответ сервера:', response.text)
