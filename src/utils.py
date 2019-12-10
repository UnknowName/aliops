from subprocess import run, PIPE, STDOUT


async def run_remote_cmd(user: str, host: str, raw_cmd: str) -> bool:
    command = "ssh {user}@{host} '{cmd}'".format(user=user, host=host, cmd=raw_cmd)
    print("Run origin command {}".format(command))
    cmd_obj = run(command, shell=True, stdout=PIPE, stderr=STDOUT)
    if cmd_obj.returncode == 0:
        return True
    print("Host {} Run cmd failed, {}".format(host, cmd_obj.stdout.decode("utf8")))
    return False


def gener_cmd(types: str, host: str, config_file: str) -> str:
    cmd_fmt = r'sed -ri "s/{types}(\s+?server\s+?{host}.*)/{flag}\1/g" {filename}'
    if types == "up":
        raw_cmd = cmd_fmt.format(types="#+", host=host, filename=config_file, flag="")
    elif types == "down":
        raw_cmd = cmd_fmt.format(types="", host=host, filename=config_file, flag="#")
    else:
        raw_cmd = ""
    return raw_cmd


if __name__ == "__main__":
    import asyncio

    loop = asyncio.get_event_loop()
    server = "128.0.100.171"
    domain = "dev.siss.io_18911"
    k8s_host = "128.0.255.7"
    cmd = gener_cmd("up", k8s_host, "/etc/nginx/conf.d/dev.siss.io.conf")
    task = loop.create_task(run_remote_cmd('root', server, cmd))
    loop.run_until_complete(task)
    loop.close()
