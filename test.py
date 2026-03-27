from google import genai
client = genai.Client(api_key='AIzaSyAk_6AEUYBWi-nmGCL-QCR1N22ZfvsEnr8')
for m in client.models.list():
    print(m.name)