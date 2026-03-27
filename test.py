<<<<<<< HEAD
from google import genai
client = genai.Client(api_key='AIzaSyAk_6AEUYBWi-nmGCL-QCR1N22ZfvsEnr8')
for m in client.models.list():
=======
from google import genai
client = genai.Client(api_key='AIzaSyAk_6AEUYBWi-nmGCL-QCR1N22ZfvsEnr8')
for m in client.models.list():
>>>>>>> ffb712560576d5b3488277ad1014a789ea03c44f
    print(m.name)