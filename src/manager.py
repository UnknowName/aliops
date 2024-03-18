import json
import pprint
import time
from typing import List,Dict
from abc import ABCMeta, abstractmethod

# CLB import
from aliyunsdkcore.client import AcsClient
from aliyunsdkslb.request.v20140515.SetBackendServersRequest import SetBackendServersRequest
from aliyunsdkecs.request.v20140526.DescribeInstancesRequest import DescribeInstancesRequest
from aliyunsdkslb.request.v20140515.DescribeVServerGroupsRequest import DescribeVServerGroupsRequest
from aliyunsdkslb.request.v20140515.SetVServerGroupAttributeRequest import SetVServerGroupAttributeRequest
from aliyunsdkslb.request.v20140515.DescribeVServerGroupAttributeRequest import DescribeVServerGroupAttributeRequest
from aliyunsdkslb.request.v20140515.DescribeLoadBalancerAttributeRequest import DescribeLoadBalancerAttributeRequest
# NLB import
from alibabacloud_tea_util import models as util_models
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_nlb20220430 import models as nlb_20220430_models
from alibabacloud_nlb20220430.client import Client as Nlb20220430Client
# DNS
from aliyunsdkalidns.request.v20150109.UpdateDomainRecordRequest import UpdateDomainRecordRequest
from aliyunsdkalidns.request.v20150109.DescribeDomainRecordsRequest import DescribeDomainRecordsRequest
# ACL
from aliyunsdkslb.request.v20140515.AddAccessControlListEntryRequest import AddAccessControlListEntryRequest

from utils import BackendInfo


class OperatorOption(object):
    def __init__(self, slb_id: str, ecs_id: str, virtual_name: str, virtual_id: str, action: str, port: str):
        self.slb_id = slb_id
        self.ecs_id = ecs_id
        self.virtual_name = virtual_name
        self.virtual_id = virtual_id
        self.action = action.lower()
        self.port = port

    def __repr__(self) -> str:
        return f"Option[slb={self.slb_id}, ecs={self.ecs_id}, virtual_id={self.virtual_id} name={self.virtual_name}]"


class AliyunLoadBalance(metaclass=ABCMeta):
    def __init__(self, key: str, secret: str, region: str):
        self.client = AcsClient(key, secret, region)

    @abstractmethod
    def get_info(self, slb_id: str) -> Dict:
        pass

    @abstractmethod
    def get_backends(self, slb_id: str, virtual_name: str) -> Dict:
        pass

    @abstractmethod
    def change_backend(self, slb_id: str, option: OperatorOption) -> Dict:
        pass

    @staticmethod
    def get_backend_details(client: AcsClient, ecs_ids: List[str]) -> List[Dict]:
        req = DescribeInstancesRequest()
        req.set_accept_format('json')
        req.set_PageSize(50)
        req.set_InstanceIds(ecs_ids)
        req.set_InstanceIds(ecs_ids)
        _response = json.loads(client.do_action_with_exception(req).decode("utf8"))
        instances = _response.get("Instances").get("Instance")
        _results = []
        for instance in instances:
            item = dict()
            item["name"] = instance.get("InstanceName")
            item["id"] = instance.get("InstanceId")
            if instance.get("InstanceNetworkType") == "classic":
                item['private_ip'] = instance.get("InnerIpAddress").get("IpAddress")[0]
            else:
                item['private_ip'] = instance.get("NetworkInterfaces").get("NetworkInterface")[0].get(
                    "PrimaryIpAddress")
            public_ips = instance.get("PublicIpAddress").get("IpAddress")
            if public_ips:
                item['public_ip'] = public_ips[0]
            _results.append(item)
        return _results


def get_slb(slb_type: str, key: str, secret: str, region: str) -> AliyunLoadBalance:
    if slb_type.upper() == "CLB":
        return CLBLoadBalance(key, secret, region)
    elif slb_type.upper() == "NLB":
        return NLBLoadBalance(key, secret, region)
    raise Exception("un support yet")


# Aliyun CLB 传统负载均衡
class CLBLoadBalance(AliyunLoadBalance):
    def get_info(self, slb_id: str) -> Dict:
        req = DescribeLoadBalancerAttributeRequest()
        req.set_accept_format('json')
        req.set_LoadBalancerId(slb_id)
        resp = json.loads(self.client.do_action_with_exception(req).decode("utf8"))
        info = dict(ip=resp.get("Address", ""), name=resp.get("LoadBalancerName"))
        return info

    def check_request(self, option: OperatorOption) -> bool:
        req = DescribeLoadBalancerAttributeRequest()
        req.set_accept_format('json')
        req.set_LoadBalancerId(option.slb_id)
        response = json.loads(self.client.do_action_with_exception(req).decode("utf8"))

    def get_backends(self, slb_id: str, virtual_name: str) -> Dict:
        resp = {}
        req = DescribeLoadBalancerAttributeRequest()
        req.set_accept_format('json')
        req.set_LoadBalancerId(slb_id)
        response = json.loads(self.client.do_action_with_exception(req).decode("utf8"))
        resp["name"] = response.get("LoadBalancerName")
        resp["ip"] = response.get("Address")
        virtual_id = ""
        if virtual_name and virtual_name != "None":
            # 有虚拟组，获取虚拟组中的机器
            req = DescribeVServerGroupsRequest()
            req.set_accept_format("json")
            req.set_LoadBalancerId(slb_id)
            try:
                req_resp = json.loads(self.client.do_action_with_exception(req).decode("utf8"))
                for vgroup in req_resp.get("VServerGroups").get("VServerGroup"):
                    if vgroup.get("VServerGroupName") == virtual_name:
                        virtual_id = vgroup.get("VServerGroupId")
                        # 通过虚拟组ID获取后端服务器信息
                        req = DescribeVServerGroupAttributeRequest()
                        req.set_accept_format("json")
                        req.set_VServerGroupId(virtual_id)
                        response = json.loads(self.client.do_action_with_exception(req).decode("utf8"))
                        break
            except Exception as e:
                return dict(status=500, text=str(e))
        backends = response.get("BackendServers", {}).get("BackendServer")
        if not backends:
            return dict(status=500, text="No Servers")
        backend_dic = {}
        for b in backends:
            backend_info = BackendInfo(b.get("ServerId"), b.get("Port"), b.get("Weight"))
            backend_dic[backend_info.id] = backend_info
        # 先获取SLB默认后端的ECS的ID，SLB只提供该API
        ecs_ids = [ecs_id for ecs_id in backend_dic]
        # 拿到ECS ID后，再获取该ECS详细信息，最终返回给页面渲染
        req = DescribeInstancesRequest()
        req.set_accept_format('json')
        req.set_PageSize(50)
        req.set_InstanceIds(ecs_ids)
        req.set_InstanceIds(ecs_ids)
        _response = json.loads(self.client.do_action_with_exception(req).decode("utf8"))
        instances = _response.get("Instances").get("Instance")
        _results = []
        for instance in instances:
            item = dict()
            item["name"] = instance.get("InstanceName")
            item["id"] = instance.get("InstanceId")
            if instance.get("InstanceNetworkType") == "classic":
                item['private_ip'] = instance.get("InnerIpAddress").get("IpAddress")[0]
            else:
                item['private_ip'] = instance.get("NetworkInterfaces").get("NetworkInterface")[0].get(
                    "PrimaryIpAddress")
            item['weight'] = backend_dic.get(item["id"]).weight
            item["port"] = backend_dic.get(item["id"]).port
            public_ips = instance.get("PublicIpAddress").get("IpAddress")
            if public_ips:
                item['public_ip'] = public_ips[0]
            if virtual_id:
                item['virtual_id'] = virtual_id
            _results.append(item)
        resp["servers"] = _results
        return resp

    def change_backend(self, slb_id: str, option: OperatorOption) -> Dict:
        if option.action == "online":
            weight = 100
        elif option.action == "offline":
            weight = 0
        else:
            return dict(status=500, text="不支持的操作")
        if option.virtual_name == "None":
            req = SetBackendServersRequest()
            req.set_accept_format('json')
            req.set_LoadBalancerId(slb_id)
            data = dict(ServerId=option.ecs_id, weight=weight)
            req.set_BackendServers([data])
        else:
            req = DescribeVServerGroupAttributeRequest()
            req.set_accept_format("json")
            req.set_VServerGroupId(option.virtual_id)
            backends = list()
            try:
                req_response = json.loads(self.client.do_action_with_exception(req).decode("utf8"))
                for backend in req_response.get("BackendServers", {}).get("BackendServer"):
                    if backend.get("ServerId") == option.ecs_id:
                        backend["Weight"] = weight
                    backends.append(backend)
                req = SetVServerGroupAttributeRequest()
                req.set_accept_format("json")
                req.set_VServerGroupId(option.virtual_id)
                req.set_BackendServers(backends)
            except Exception as e:
                return dict(status=500, text=str(e))
        try:
            response = self.client.do_action_with_exception(req)
            return dict(status=200, text=response.decode("utf8"))
        except Exception as e:
            return dict(status=500, text=str(e))


# Aliyun NBL 网络负载均衡
class NLBLoadBalance(AliyunLoadBalance):
    def __init__(self, key: str, secret: str, region: str):
        AliyunLoadBalance.__init__(self, key, secret, region)
        config = open_api_models.Config(access_key_id=key, access_key_secret=secret)
        config.endpoint = "nlb.cn-shenzhen.aliyuncs.com"
        self.region = region
        self.asc_client = AcsClient(key, secret, region)
        self.client = Nlb20220430Client(config)

    def get_info(self, slb_id: str) -> Dict:
        pass

    def get_backends(self, slb_id: str, virtual_name: str) -> Dict:
        response = {}
        req = nlb_20220430_models.ListServerGroupsRequest(region_id=self.region, server_group_names=[virtual_name])
        runtime = util_models.RuntimeOptions()
        try:
            data = self.client.list_server_groups_with_options(req, runtime).to_map()
            group_id = data.get("body").get("ServerGroups")[0].get("ServerGroupId")
            # 获取后端服务器信息
            servers_req = nlb_20220430_models.ListServerGroupServersRequest(
                region_id=self.region,
                server_group_id=group_id,
            )
            resp = self.client.list_server_group_servers_with_options(servers_req, runtime).to_map()
            storage = {}
            for server in resp.get("body").get("Servers"):
                re = dict(
                    port=server.get("Port"),
                    weight=server.get("Weight"),
                    virtual_id=server.get("ServerGroupId")
                )
                storage[server.get("ServerId")] = re
            backends = self.get_backend_details(self.asc_client, [ecs for ecs in storage])
            # 将backend的所有属于附加进storage的元素的里面
            for backend in backends:
                re = storage[backend.get("id")]
                re.update(backend)
            response["servers"] = list([server for server in storage.values()])
            # 获取NLB名称Ip信息
            req = nlb_20220430_models.GetLoadBalancerAttributeRequest(region_id=self.region, load_balancer_id=slb_id)
            data = self.client.get_load_balancer_attribute_with_options(req, runtime).to_map()
            nlb_name = data.get("body").get("LoadBalancerName")
            response["name"] = nlb_name
            ips = data.get("body").get("ZoneMappings")
            for ip in ips:
                if ip.get("ZoneId") != "cn-shenzhen-d":
                    continue
                for d in ip.get("LoadBalancerAddresses"):
                    response["ip"] = d.get("PrivateIPv4Address")
        except Exception as error:
            print(f"error {error}")
            return dict(status=500, error=str(error))
        return response

    def change_backend(self, slb_id: str, option: OperatorOption) -> Dict:
        if option.action.lower() == "online":
            weight = 100
        elif option.action.lower() == "offline":
            weight = 0
        else:
            return dict(status=500, text="unknown option")
        runtime = util_models.RuntimeOptions()
        change_server = nlb_20220430_models.UpdateServerGroupServersAttributeRequestServers(
            server_id=option.ecs_id,
            server_type='Ecs',
            weight=weight,
            port=int(option.port),
        )
        req = nlb_20220430_models.UpdateServerGroupServersAttributeRequest(
            region_id=self.region,
            servers=[change_server],
            server_group_id=option.virtual_id,
        )
        try:
            resp = self.client.update_server_group_servers_attribute_with_options(req, runtime)
            group_id = resp.to_map().get("body").get("ServerGroupId")
            query_req = nlb_20220430_models.ListServerGroupServersRequest(
                region_id=self.region,
                server_group_id=group_id
            )
            loading = True
            while loading:
                data = self.client.list_server_group_servers_with_options(query_req, runtime).to_map()
                servers = data.get("body").get("Servers")
                for server in servers:
                    if server.get("ServerId") != option.ecs_id:
                        continue
                    if server.get("Status") == "Available":
                        loading = False
                        break
                time.sleep(0.7)
                resp = dict(servers=servers, status=200)
            return dict(status=200, text=json.dumps(resp))
        except Exception as e:
            print(f"err {e}")
            return dict(status=500, text=str(e))


class ClassicAgent(object):
    def __init__(self, key: str, secret: str, region: str):
        self.client = AcsClient(key, secret, region)


class DNSAgent(ClassicAgent):
    def get_record(self, domain: str, keyword: str) -> Dict:
        req = DescribeDomainRecordsRequest()
        req.set_accept_format('json')
        req.set_DomainName(domain)
        req.set_Lang("en")
        req.set_PageSize(20)
        req.set_KeyWord(keyword)
        try:
            response = self.client.do_action_with_exception(req)
            resp = str(response, encoding='utf-8')
            detail = json.loads(resp)
            return detail
        except Exception as e:
            # print(f"error {e}")
            return dict(status=500, text=str(e))

    def change_record(self, domain: str, record_name: str, record_id: str, ip: str) -> dict:
        req = UpdateDomainRecordRequest()
        req.set_accept_format('json')
        req.set_RecordId(record_name)
        req.set_RR(domain)
        req.set_Type("A")
        req.set_Value(ip)
        try:
            response = self.client.do_action_with_exception(req)
            if json.loads(response.decode("utf8")).get("RecordId") == record_id:
                return dict(status=200, msg="OK")
            return dict(status=400, msg="not found")
        except Exception as e:
            return dict(status=500, msg=str(e))


class ACLAgent(ClassicAgent):
    def add_ip(self, ip: str, comment: str) -> Dict:
        req = AddAccessControlListEntryRequest()
        req.set_accept_format('json')
        req.set_AclId("acl-wz9lkxbst9kk1v57lz3ha")
        entries = [{"entry": "{}/32".format(ip), "comment": comment}]
        req.set_AclEntrys(entries)
        try:
            self.client.do_action_with_exception(req)
        except Exception as e:
            return dict(status=str(e))
        return dict(status="ok")


if __name__ == '__main__':
    d1 = dict(name="cheng")
    d2 = dict(sex="man")
    print(json.dumps(d2))
