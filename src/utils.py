import re
import yaml
from functools import reduce
from subprocess import run, PIPE, STDOUT

CONFIG_FILE = "config.yml"


"""
def merge_results(results: list):
    merged = set()
    for i, result in enumerate(results):
        if i == 0:
            merged = set(result) | merged
        merged = set(result) & merged
    return tuple(merged)
"""


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

    def set_upstreams_status(self, upstreams: list, status: str, config_path: str):
        cmd_fmt = r'sed --follow-symlinks -ri "s/{status}(\s+?server\s+?\b{host}\b.*)/{flag}\1/g" {filename}'
        raw_cmd = ""
        for _upstream in upstreams:
            if status == "up":
                _cmd = cmd_fmt.format(status="#+", host=_upstream, filename=config_path, flag="")
            elif status == "down":
                _cmd = cmd_fmt.format(status="", host=_upstream, filename=config_path, flag="#")
            else:
                _cmd = ""
            raw_cmd += "{}&&".format(_cmd)
        _ok, _stdout = self._execute_cmd(raw_cmd.rstrip("&&"))
        if _ok:
            _ok, _stdout = self._reload_service()
        else:
            return False, _stdout
        return _ok, _stdout

    def check_config(self):
        return self._execute_cmd("nginx -t")

    def _reload_service(self):
        return self._execute_cmd("nginx -t && nginx -s reload")


class AppConfig(object):
    def __init__(self, config_path: str = "") -> None:
        _config_file = config_path if config_path else CONFIG_FILE
        with open(_config_file) as f:
            conf_dict = yaml.safe_load(f)
        self._config_dic = conf_dict

    def get_all_domains(self, name: str = "") -> list:
        """Support change NGINX upstream's domains"""
        _all_domains = self.get_attr("domains")
        if name == "nginx":
            _attr = "backend_port"
        elif name == "slb":
            _attr = "slbs"
        else:
            _attr = ""
        _domains = list()
        for _domain_dic in _all_domains:
            for _domain, _value in _domain_dic.items():
                if _attr and _value.get(_attr):
                    _domains.append(_domain)
        return _domains

    def get_attr(self, attr: str) -> dict:
        return self._config_dic.get(attr)

    def get_domain(self, domain: str) -> dict:
        _domains = self._config_dic.get("domains")
        for _index, _domain in enumerate(_domains):
            if domain in _domain:
                return _domain[domain]

    def get_domain_nginxs(self, domain: str) -> tuple:
        _domain_dict = self.get_domain(domain)
        _exist_nginx = _domain_dict.get("nginx")
        _nginx = _exist_nginx if _exist_nginx else self.get_attr("nginx")
        return _nginx.get("ssh_user"), tuple(_nginx.get("hosts"))


def check_equal(data: list) -> tuple:
    def _check(x, y):
        if x == y:
            return x
        return False
    return reduce(_check, data)


if __name__ == "__main__":
    """
    import asyncio

    loop = asyncio.get_event_loop()
    server = "128.0.100.171"
    domain = "dev.siss.io_18911"
    k8s_host = "128.0.255.7"
    cmd = gener_cmd("up", k8s_host, "/etc/nginx/conf.d/dev.siss.io.conf")
    task = loop.create_task(run_remote_cmd('root', server, cmd))
    loop.run_until_complete(task)
    loop.close()
    """
    test_domain = "dev.siss.io"
    config = AppConfig("config.yml")
    print(config.get_all_domains("slb"))