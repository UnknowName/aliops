import re
from functools import reduce
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
    cmd_fmt = r'sed --follow-symlinks -ri "s/{types}(\s+?server\s+?\b{host}\b.*)/{flag}\1/g" {filename}'
    if types == "up":
        raw_cmd = cmd_fmt.format(types="#+", host=host, filename=config_file, flag="")
    elif types == "down":
        raw_cmd = cmd_fmt.format(types="", host=host, filename=config_file, flag="#")
    else:
        raw_cmd = ""
    return raw_cmd


def merge_results(results: list):
    merged = set()
    for i, result in enumerate(results):
        if i == 0:
            merged = set(result) | merged
        merged = set(result) & merged
    return tuple(merged)


class Gateway(object):
    def __init__(self, user: str, host: str) -> None:
        self.ssh_user = user
        self.ssh_host = host

    def _execute_cmd(self, command: str):
        _cmd = r"""ssh {user}@{host} '{command}'""".format(
            user=self.ssh_user, host=self.ssh_host, command=command
        )
        cmd_obj = run(_cmd, shell=True, stdout=PIPE, stderr=STDOUT)
        output = cmd_obj.stdout.decode("utf8")
        if cmd_obj.returncode == 0:
            return True, output
        return False, output

    def _filter_upstream(self, line: str):
        reg = re.compile(r'(\s+)?#?(\s+)?(\s+)?\bserver\b\s+(\d{1,3}\.){3}\d{1,3}(:\d+)?')
        try:
            # return is "# server 128.0.255.10:80" or "server 128.0.255.10:80"
            return reg.match(line).group().strip()
        except AttributeError:
            return ""

    # 只返回指定端口的服务器，在线/下线状态由客户端JS判断
    def _get_upstream_servers(self, config_file: str) -> (bool, set):
        """返回Set类型，后续的检查相等函数用得上"""
        cmd_fmt = r"""grep -E "\s+#?\bserver\b\s+.*;" {config_file}"""
        command = cmd_fmt.format(user=self.ssh_user, host=self.ssh_host, config_file=config_file)
        ok, stdout = self._execute_cmd(command)
        if ok and stdout:
            all_server = set()
            for line in stdout.split('\n'):
                if not line:
                    continue
                upstream = self._filter_upstream(line)
                if upstream:
                    all_server.add(upstream)
            return True, all_server
        err_msg = stdout
        return False, err_msg

    def get_domain_servers(self, config_file: str, port: str):
        ok, output = self._get_upstream_servers(config_file)
        if ok:
            hosts = set()
            for _upstream in output:
                _, _port = _upstream.split(":")
                if _port == str(port):
                    upstream = _upstream.strip(" ")
                    if upstream.startswith("#"):
                        upstream = re.sub(r'#\s+', '#', _upstream)
                    hosts.add(upstream)
            return True, hosts
        return False, output

    def check_config(self):
        return self._execute_cmd("nginx -t")

    def reload_service(self):
        ok, _ = self._execute_cmd("nginx -t && nginx -s reload")
        return ok


def check_equal(data: list):
    def _check(x, y):
        if x == y:
            return x
        return False
    return reduce(_check, data)


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