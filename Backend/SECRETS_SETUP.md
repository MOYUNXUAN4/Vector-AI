# DeepSeek key setup

The application reads the DeepSeek key from the `DEEPSEEK_API_KEY` environment variable. No real credential belongs in source code.

Before starting the server in PowerShell:

```powershell
$env:DEEPSEEK_API_KEY = "your_real_DeepSeek_key"
python master_server.py
```

Do not commit `.env` or any real key. Revoke any key that was previously stored in source code before making the repository public.
