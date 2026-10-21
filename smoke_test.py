import anthropic

client = anthropic.Anthropic()

response = client.messages.create(model="claude-sonnet-5-5", messages=[{"role": "user", "content": "Say hello in five words"}], max_tokens = 256)

print(response)