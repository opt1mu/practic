from aiohttp import web

async def handle_ok(request):
    return web.json_response({"status": "success", "message": "Raw performance"})

async def handle_challenge(request):
    if request.headers.get("X-Challenge-Passed") != "true":
        return web.json_response(
            {"error": "JavaScript Challenge Required", "action": "solve_captcha"},
            status=403
        )
    return web.json_response({"status": "authenticated"})

app = web.Application()
app.router.add_get('/ok', handle_ok)
app.router.add_post('/ok', handle_ok)
app.router.add_get('/challenge', handle_challenge)

if __name__ == '__main__':
    web.run_app(app, port=8080)