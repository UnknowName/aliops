import re
import yaml
from functools import reduce
from subprocess import run, PIPE, STDOUT

CONFIG_FILE = "config.yml"


class Gateway(object):
    _server_reg = re.compile(r'(\s+)?(#+)?(\s+)?(\s+)?\bserver\b\s+(\d{1,3}\.){3}\d{1,3}(:\d+)?')
    _weight_reg = re.compile(r".*weight=(\d{,3}).*")
    _tag = "W"

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

    def _filter_upstream(self, line: str) -> str:
        try:
            # return is "# server 128.0.255.10:80" or "server 128.0.255.10:80"
            return self._server_reg.match(line).group().strip()
        except AttributeError:
            return ""

    def _get_server_weight(self, line: str) -> str:
        result = self._weight_reg.match(line)
        if result:
            return result.group(1)
        else:
            return "1"

    def fmt_down_servers(self, servers: list, operation: str, config_file: str):
        if not servers:
            return ""
        else:
            _cmds = list()
            if operation == "down":
                _fmt = r'sed --follow-symlinks -ri "s/(\s+?server\s+?\b{host}\b.*)/#\1/g" {filename}'
            elif operation == "down-weight":
                _fmt = r'sed --follow-symlinks -ri "s/(\s+?server\s+?\b{host}\b.*)/{server}/g" {filename}'
            else:
                return ""
            for server_with_weight in servers:
                if server_with_weight == "":
                    continue
                _server, _weight = server_with_weight.split(self._tag)
                server = "server {} weight={};".format(_server, _weight)
                _cmds.append(_fmt.format(host=_server, server=server, filename=config_file))
            return "&&".join(_cmds)

    def fmt_up_servers(self, servers: list, operation: str, config_file: str):
        if not servers:
            return ""
        else:
            _cmds = list()
            if operation == "up,up-weight":
                # print("已下线机器修改权重并上线")
                _fmt = r'sed --follow-symlinks -ri "s/(#+?\s+?server\s+?\b{host}\b.*)/{server}/g" {filename}'
            elif operation == "up":
                # print("已下线机器只上线")
                _fmt = r'sed --follow-symlinks -ri "s/#+?\s+?(\s+?server\s+?\b{host}\b.*)/\1/g" {filename}'
            elif operation == "up-weight":
                # print("已下线机器只修改权重")
                _fmt = r'sed --follow-symlinks -ri "s/(\s+?server\s+?\b{host}\b.*)/{server}/g" {filename}'
            else:
                return ""
            for server_with_weight in servers:
                if server_with_weight == "":
                    continue
                _server, _weight = server_with_weight.split(self._tag)
                server = "server {} weight={};".format(_server, _weight)
                _cmds.append(_fmt.format(host=_server, server=server, filename=config_file))
            return "&&".join(_cmds)

    # 只返回指定端口的服务器，在线/下线状态由客户端JS判断
    def _get_upstream_servers(self, config_file: str) -> (bool, set):
        """返回Set类型，后续的检查相等函数用得上"""
        cmd_fmt = r"""grep -E "\s+?#+?\bserver\b\s+.*;" {config_file}"""
        command = cmd_fmt.format(user=self.ssh_user, host=self.ssh_host, config_file=config_file)
        ok, stdout = self._execute_cmd(command)
        if ok and stdout:
            all_server = set()
            for line in stdout.split('\n'):
                if not line:
                    continue
                upstream, weight = self._filter_upstream(line), self._get_server_weight(line)
                if upstream:
                    all_server.add("{}{}{}".format(upstream, self._tag, weight))
            return True, all_server
        err_msg = stdout
        return False, err_msg

    def get_domain_servers(self, config_file: str, port: str):
        ok, output = self._get_upstream_servers(config_file)
        if ok:
            hosts = set()
            for _upstream in output:
                _server_port, weight = _upstream.split(self._tag)
                _, _port = _server_port.split(":")
                if _port == str(port):
                    upstream = _upstream.strip(" ")
                    if upstream.startswith("#"):
                        upstream = re.sub(r'#+', '#', _upstream)
                        upstream = re.sub(r'#\s+', '#', upstream)
                    hosts.add(upstream)
            return True, hosts
        return False, output

    def set_upstream_with_weight(self, upstream: dict, operation: dict, config_path: str):
        down_server_cmds = self.fmt_down_servers(upstream.get("down_servers"), operation.get("down", ""), config_path)
        up_server_cmds = self.fmt_up_servers(upstream.get("up_servers"), operation.get("up", ""), config_path)
        if down_server_cmds and up_server_cmds:
            all_cmds = "{}&&{}".format(down_server_cmds, up_server_cmds)
        elif down_server_cmds and not up_server_cmds:
            all_cmds = down_server_cmds
        elif up_server_cmds and not down_server_cmds:
            all_cmds = up_server_cmds
        else:
            all_cmds = ""
        print("*" * 20)
        print(all_cmds)
        print("*" * 20)
        _ok, _stdout = self._execute_cmd(all_cmds)
        if _ok:
            _ok, _stdout = self._reload_service()
        else:
            return False, _stdout
        return _ok, _stdout

    def set_upstreams_status(self, upstreams: list, status: str, config_path: str):
        cmd_fmt = r'sed --follow-symlinks -ri "s/{status}(\s+?server\s+?\b{host}\b.*)/{flag}\1/g" {filename}'
        cmds = list()
        for _upstream in upstreams:
            if status == "up":
                _cmd = cmd_fmt.format(status="#+", host=_upstream, filename=config_path, flag="")
            elif status == "down":
                _cmd = cmd_fmt.format(status="", host=_upstream, filename=config_path, flag="#")
            else:
                _cmd = ""
            cmds.append(_cmd)
        _ok, _stdout = self._execute_cmd("&&".join(cmds))
        if _ok:
            _ok, _stdout = self._reload_service()
        else:
            return False, _stdout
        return _ok, _stdout

    def set_upstream_status(self, upstream: dict, config_path: str):
        """
        :param upstream: {"down_servers":["1.1.1.1", "2.2.2.2"], "up_servers":["3.3.3.3","4.4.4.4"]}
        :param config_path:
        :return:
        """
        _down_servers = upstream.get("down_servers", [])
        _up_servers = upstream.get("up_servers", [])
        _cmd_fmt = r'sed --follow-symlinks -ri "s/{status}(\s+?server\s+?\b{host}\b.*)/{flag}\1/g" {filename}'
        _cmds = list()
        if _down_servers and _down_servers[0] != "":
            [_cmds.append(_cmd_fmt.format(status="#+", host=_upstream, filename=config_path, flag=""))
                for _upstream in _down_servers
            ]
        if _up_servers and _up_servers[0] != "":
            [_cmds.append(_cmd_fmt.format(status="", host=_upstream, filename=config_path, flag="#"))
                for _upstream in _up_servers
            ]
        _ok, _stdout = self._execute_cmd("&&".join(_cmds))
        if _ok:
            _ok, _stdout = self._reload_service()
        else:
            return False, _stdout
        return _ok, _stdout

    def _reload_service(self):
        return self._execute_cmd("nginx -t && nginx -s reload")


class AppConfig(object):
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            obj = super(AppConfig, cls).__new__(cls)
            cls._instance = obj
        return cls._instance

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
        elif name == "dns":
            _attr = "ips"
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
        if isinstance(x, bool):
            return False
        if x[0] == y[0]:
            _x = (elem.replace(" ", "") for elem in x[1])
            _y = (elem.replace(" ", "") for elem in y[1])
            if tuple(_x) == tuple(_y):
                return x
        return False
    return reduce(_check, data)


if __name__ == "__main__":
    """
    test_domain = "dev.siss.io"
    config = AppConfig("config.yml")
    print(config.get_domain("dev.siss.io"))
    """
    user = "user"
    host = "128.0.255.10"
    g = Gateway(user, host)
    # servers = ["128.0.255.29:8080W20"]
    down_servers = ["128.0.255.27:8080W20"]
    up_servers = ['']
    op = dict(up="up", down="down")
    test_servers = dict(up_servers=up_servers, down_servers=down_servers)
    g.set_upstream_with_weight(test_servers, op, "test.conf")

