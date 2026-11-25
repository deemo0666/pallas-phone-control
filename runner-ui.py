"""Forward the upstream sign-in page between the two device loopbacks."""
import asyncio
import os
import re


DONE = '手机操控已安装并已连接 Pallas'
INSTALL_STAGES = {'OK Personal Team profile verified and runner signed', 'OK Runner installation confirmed',
                  'OK Pallas runner installed and linked'}


# `command` replaces the runner arguments (reveal.py signs without a device); `stages` are the
# lines that must all appear, and `success` is the stage the job ends on when they did.
async def run(root, home, ipa, port, config, bridge, relay, command=None, stages=INSTALL_STAGES, success=DONE):
    web = bridge(action='web-relay')['data']
    print('已建立签装页面转发', flush=True)
    async def worker():
        while True:
            try:
                reader, writer = await asyncio.open_connection('10.0.2.2', web['reverse'])
                try:
                    writer.write(web['key'].encode('ascii'))
                    await writer.drain()
                    if await reader.readexactly(1) == b'G':
                        await relay(reader, writer, web['port'])
                finally:
                    writer.close()
            except (OSError, asyncio.IncompleteReadError):
                await asyncio.sleep(.15)

    workers = [asyncio.create_task(worker()) for _ in range(8)]
    env = dict(os.environ, PATH=str(root) + ':' + os.environ['PATH'], PALLAS_WEB_PORT=str(web['port']))
    process = None
    outcome = '签装中断'
    try:
        argv = command or ['runner', '--web', '--home', str(home), '--ipa', str(ipa), '--port', str(port),
                           '--anisette', 'https://ani.iloader.app']
        process = await asyncio.create_subprocess_exec(str(root/'pallasboot'), *argv,
            env=env, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        seen = set()
        async for raw in process.stdout:
            line = raw.decode(errors='replace').strip()
            if line in stages:
                seen.add(line)
                print(line, flush=True)
            elif match := re.fullmatch(r'http://127\.0\.0\.1:(\d+)(/[a-f0-9]{32}/)', line):
                if int(match[1]) != web['port'] or not bridge(action='signer-page', path=match[2])['ok']:
                    raise RuntimeError('无法打开本机签装页面')
                print('已发布本机签装页面', flush=True)
            elif "page is open in Pallas" in line:
                print('已发布本机签装页面', flush=True)
            elif "couldn't serve the page" in line:
                raise RuntimeError('签装器无法监听本机登录页面')
            elif line == 'OK Existing Apple session verified':
                print('已复用本机 Apple 登录', flush=True)
            elif 'Apple 7460' in line and not line.startswith('Stopped:'):
                print('Apple 开发证书名额已满（Apple 7460），等待在 iPad 上选择', flush=True)
            elif line.startswith('[4/7]'):
                print('等待在 iPad 上登录免费 Apple 账号', flush=True)
            elif line.startswith('Stopped:'):
                # Detailed upstream messages stay in the on-device page.
                outcome = '签装失败：' + line.removeprefix('Stopped:').strip()[:120]
                print(outcome, flush=True)
        if await process.wait() == 0 and seen == stages:
            outcome = success
            return 0
        return 1
    finally:
        if process and process.returncode is None:
            process.kill()
            await process.wait()
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        bridge(action='end-web', outcome=outcome)
