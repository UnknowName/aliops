import re
import yaml
from typing import Dict
from functools import reduce
from subprocess import run, PIPE, TimeoutExpired

CONFIG_FILE = "config.yml"


class CommandError(Exception):
    def __init__(self, msg: str):
        print("CommandError({})".format(msg))


class _BackendServer(object):
    _weight_reg = re.compile(r".*weight=(\d{,3}).*")

    # 初始化传入NGINX的upstream里面的一条记录;如 server 128.0.0.10:80 weight=10, max_failed=10;
    def __init__(self, upstream_item: str):
        _result = self._weight_reg.match(upstream_item)
        self.weight = _result.group(1) if _result else "1"
        if upstream_item[0] == "#":
            self.is_offline = True
            _, _host, *_others = re.sub(r'#\s+', '', upstream_item).split()
        else:
            self.is_offline = False
            _, _host, *_others = upstream_item.split()
        self.host = _host
        self.others = "".join([attr for attr in _others if not attr.startswith("weight")])

    # 格式化成NGINX标准的upstream中的样式，如: server 128.0.0.10:80 weight=10 max_failed=3;
    def format(self) -> str:
        if self.is_offline:
            return "#server {} weight={} {};".format(self.host, self.weight, self.others)
        return "server {} weight={} {};".format(self.host, self.weight, self.others)

    # 兼容之前的接口
    def string(self) -> str:
        _fmt = "#server {}W{}" if self.is_offline else "server {}W{}"
        return _fmt.format(self.host, self.weight)

    def __repr__(self) -> str:
        _fmt = "#server {}W{}" if self.is_offline else "server {}W{}"
        return _fmt.format(self.host, self.weight)


class GatewayNGINX(object):
    _cmd_fmt = "ssh root@{host} '{command}'"
    # 提取后端服务器正则，后端必须要带端口号
    _filter_fmt = r"""sed -rn "s/(#?.*\bserver\b.*\b:{port}\b.*).*;/\1/p" {config_file}"""
    # 上线正则，无需区分是不是要修改权重，因为权重已经传进来
    _up_fmt = (r'sed --follow-symlinks -ri '
               r'"s/#{1,}(.*\bserver\b\s+?\b{host}\b.*)weight=\w+?(.*;)/\1weight={v}\2/g" {config_file}')
    # 下线正则
    _down_fmt = (r'sed --follow-symlinks -ri '
                 r'"s/#{0,}(.*\bserver\b\s+?\b{host}\b.*)weight=\w+?(.*;)/#\1weight={v}\2/g" {config_file}')
    # 只修改权重正则
    _weight_fmt = (r'sed --follow-symlinks -ri '
                   r'"s/(.*\bserver\b\s+?\b{host}\b.*)weight=\w+?(.*;)/\1weight={v}\2/g" {config_file}')

    def __init__(self, user: str, host: str):
        self._user = user
        self._host = host

    def _execute(self, cmd: str) -> (bool, str):
        _command = self._cmd_fmt.format(host=self._host, command=cmd)
        # 空命令，直接返回True
        if not cmd.split():
            return True, ""
        try:
            std = run(_command, shell=True, timeout=5, stdout=PIPE, stderr=PIPE)
            stdout = std.stdout.decode("utf8", errors="ignore")
            if std.returncode and std.stderr:
                err_output = std.stderr.decode("utf8", errors="ignore")
                raise CommandError(err_output)
        except CommandError:
            return False, ""
        except TimeoutExpired:
            return False, ""
        return True, stdout

    def _reload(self) -> bool:
        result, _ = self._execute("nginx -t && nginx -s reload")
        return result

    # 如果返回的bool为False，说明数据获取失败
    def get_servers(self, config_file: str, port: str) -> (bool, set):
        servers = set()
        cmd = self._filter_fmt.format(config_file=config_file, port=port)
        _result, _plain_str = self._execute(cmd)
        if _result and _plain_str:
            for line in _plain_str.split("\n"):
                if not line:
                    continue
                server = _BackendServer(line.strip())
                servers.add(server.string())
            return True, servers
        return False, servers

    def change_servers(self, upstream: Dict, operation: Dict, config_file: str) -> (bool, str):
        down_option, up_option = operation.get("down", ""), operation.get("up", "")
        # down是要下线的机器['128.0.0.10:80W10']
        down_servers = [server for server in upstream.get("down_servers", set()) if server != ""]
        up_servers = [server for server in upstream.get("up_servers", set()) if server != ""]
        cmds = []
        if up_option and up_servers:
            for _server_weight in up_servers:
                try:
                    _server, _weight = _server_weight.split("W")
                    _cmd = self._up_fmt.format(host=_server, v=_weight, config_file=config_file)
                    cmds.append(_cmd)
                except ValueError:
                    return False, "待上线服务器数据格式有误"
        if down_option and down_servers:
            if down_option == "down-weight":
                _fmt = self._weight_fmt
            else:
                _fmt = self._down_fmt
            for _server_weight in down_servers:
                _server, _weight = _server_weight.split("W")
                _cmd = _fmt.format(host=_server, v=_weight, config_file=config_file)
                cmds.append(_cmd)
        cmd = "&&".join(cmds)
        if not cmd.split():
            return True, ""
        success, output = self._execute(cmd)
        if not success:
            return False, ""
        if self._reload():
            return True, ""
        return False, ""


class AppConfig(object):
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            obj = super(AppConfig, cls).__new__(cls)
            cls._instance = obj
        return cls._instance

    def __init__(self, config_path: str = "") -> None:
        _config_file = config_path if config_path else CONFIG_FILE
        with open(_config_file, encoding="utf8") as f:
            conf_dict = yaml.safe_load(f)
        self._config_dic = conf_dict

    def get_all_domains(self, name: str = "") -> list:
        """Support change NGINX upstream  domains"""
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
        return {}

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
            _x = {elem.replace(" ", "") for elem in x[1]}
            _y = {elem.replace(" ", "") for elem in y[1]}
            if _x == _y:
                return x
        return False

    return reduce(_check, data)


if __name__ == "__main__":
    test_domain = "dev.siss.io"
    config = AppConfig("config.yml")
    print(config.get_domain("dev.siss.io"))
    test_user = "user"
    test_host = "128.0.255.10"
    g = GatewayNGINX(test_user, test_host)
    """
    down_servers = ["128.0.255.27:8080W20"]
    up_servers = ['']
    op = dict(up="up", down="down")
    test_servers = dict(up_servers=up_servers, down_servers=down_servers)
    g.set_upstream_with_weight(test_servers, op, "test.conf")
    info = "server 172.16.33.4:80"
    info2 = "#       server     172.16.202.249:80     max_fails=3 weight=80;"
    info3 = "server 172.16.202.244:80  weight=10;"
    serve1 = _BackendServer(info2)
    print(serve1)
    print(serve1.format())
    """
