# django-ftp-jumper
基于django的ftp客户端，所有前端页面操作，发送到服务端，然后转换成ftp api操作远程ftp服务器。

### 使用方法：
拷贝ftp_client到你的django项目中

修改settings.py. 增加ftp_client到INSTALLED_APPS中

INSTALLED_APPS = (
    ..., 
    'ftp_client'
)

将url配置增加到项目的url中
url('ftp-client/', include('ftp_client.urls', namespace='ftp_client'))

在constant.py中配置ftp服务器地址和连接模式，支持主动和被动连接

### 特别说明：
基于https://github.com/author135135/django-ftp-client/ 项目修改。修改其代码，完善部分不可用的功能，增加部分功能。优化页面，修改BUG。
