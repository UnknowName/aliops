import yaml
from typing import Dict, List

CONFIG_FILE = "config.yml"


class ESConfig(object):
    def __init__(self, data: dict):
        self.addr = data.get("addr")
        self.port = data.get("port")
        self.index = data.get("index")


class APIConfig(object):
    def __init__(self, data: dict):
        self.key = data.get("key")
        self.secret = data.get("secret")
        self.region = data.get("region")


class SLBConfig(object):
    def __init__(self, data: dict):
        self.type = data.get("type")
        self.backend_virtual_name = data.get("backend_virtual_name")
        self.ids = {k: None for k in data.get("ids", [])}

    def __repr__(self) -> str:
        return f"SLBConfig(type={self.type} ids={self.ids}, backend={self.backend_virtual_name})"


class NGINXConfig(object):
    def __init__(self, data: dict):
        self.ssh_user = data.get("ssh_user")
        self.hosts = data.get("hosts", [])
        self.backend_port = data.get("backend_port")
        self.config_file = data.get("config_file")


class DomainConfig(object):
    def __init__(self, data: dict):
        self.display: str = data.get("display")
        self.domain: str = data.get("domain")
        self.ip: dict = {ip: None for ip in data.get("ips", [])}
        self.nginx: NGINXConfig = NGINXConfig(data.get("nginx")) if data.get("nginx") else None
        self.slb: SLBConfig = SLBConfig(data.get("slb")) if data.get("slb") else None
        self.invisible = data.get("invisible", False)
        self.relatives: List[str] = data.get("relatives", [])


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
        domain_confs = conf_dict.get("domains")
        self.domain: Dict[str, DomainConfig] = {k.get("display"): DomainConfig(k) for k in domain_confs}
        self.slb_api: APIConfig = APIConfig(conf_dict.get("slb_api"))
        self.dns_api: APIConfig = APIConfig(conf_dict.get("dns_api"))
        self.es: ESConfig = ESConfig(conf_dict.get("es"))
        self.nginx: NGINXConfig = NGINXConfig(conf_dict.get("nginx"))

    @property
    def api(self) -> APIConfig:
        return self.slb_api

    def get_domain_config(self, display: str) -> DomainConfig:
        return self.domain[display]

