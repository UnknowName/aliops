import yaml

_config = "config.yml"


def _get_attr(attr: str):
    with open(_config) as f:
        conf_dict = yaml.safe_load(f)
        return conf_dict.get(attr)


def get_backends(domain_name: str) -> list:
    backends = list()
    _domains = _get_attr('domains')
    for domain in _domains:
        for k, v in domain.items():
            if k == domain_name:
                backends = v.get("backends")
    return backends


async def get_domain_config(domain_name: str, domain_attr: str) -> list:
    attrs = list()
    _domains = _get_attr('domains')
    for domain in _domains:
        for k, v in domain.items():
            if k == domain_name:
                attrs = v.get(domain_attr, [])
    return attrs


def _get_domains() -> list:
    _domains = _get_attr('domains')
    _lst = []
    for _dict in _domains:
        for k, _ in _dict.items():
            _lst.append(k)
    return _lst


async def get_domain_nginxs(domain: str):
    domain_ngx = await get_domain_config(domain, 'nginx')
    if isinstance(domain_ngx, dict) and domain_ngx:
        nginxs = domain_ngx.get("hosts")
        nginx_user = domain_ngx.get("ssh_user")
    else:
        global_nginx = _get_attr('nginx')
        nginxs = global_nginx.get("hosts")
        nginx_user = global_nginx.get("ssh_user")
    return nginxs, nginx_user


_nginx = _get_attr('nginx')
NGINXS = _nginx.get('hosts')
NGINX_USER, NGINX_PASSWORD = _nginx.get('ssh_user'), _nginx.get('ssh_password')
DOMAINS = _get_domains()
AESKEY = _get_attr("api").get("aeskey")
AESKEY_SECRET = _get_attr("api").get("aeskey_secret")
REGION = _get_attr("api").get("region")
DNS_AESKEY = _get_attr("dns_api").get("aeskey")
DNS_SECRET = _get_attr("dns_api").get("aeskey_secret")
DNS_REGION = _get_attr("dns_api").get("region")


if __name__ == '__main__':
    print(AESKEY, AESKEY_SECRET)
    import asyncio
    # nginx = get_domain_config("www.unknowname.win", "nginx")
    config = get_domain_config("www.unknowname.win", 'config_file')
    print(asyncio.run(config))