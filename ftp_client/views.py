import os
import ftplib
import stat
from django.shortcuts import render
from django.http import HttpResponse, HttpResponseForbidden
from ftp_client.forms import ConnectionForm
from json import JSONEncoder
from dateutil import parser
from .constant import *


def index(request):
    connection_form = ConnectionForm()
    manager = FtpClientLocalManager()

    return render(request, template_name='ftp_client/index.html', context={
        'connection_form': connection_form,
        'local_dir': manager.get_dir_content(),
        'local_dir_path': manager.get_dir(),
    })


def connect(request):
    if request.META['REQUEST_METHOD'] == 'GET':
        return HttpResponseForbidden('403 Access denied')

    connection_form = ConnectionForm(request.POST)
    manager = FtpClientRemoteManager()

    response = {
        'errors': None,
        'success': False,
        'disconnect': False,
        'remote_dir': None,
        'remote_dir_path': None,
    }


    if request.POST['connect_type'] == 'connect':
        if connection_form.is_valid():
            manager.add_connection(FTP_HOST, FTP_PORT, FTP_USER, FTP_PASSWD, FTP_MODE)
            response['remote_dir_content'] = manager.get_dir_content()
            response['remote_dir_path'] = manager.get_connection().pwd()
            response['success'] = True
        else:
            response['errors'] = connection_form.errors

    elif request.POST['connect_type'] == 'disconnect':
        manager.close_connection()
        response['disconnect'] = True

    return HttpResponse(JSONEncoder().encode(response))


def tasks(request):
    if 'task' not in request.POST:
        return HttpResponseForbidden('403 Access denied')

    response = dict()

    if request.POST['type'] == 'remote':
        manager = FtpClientRemoteManager()
    else:
        manager = FtpClientLocalManager()

    if request.POST['task'] == 'change_dir':
        manager.set_dir(request.POST['dir'])
        response['cur_dir'] = manager.get_dir()
    elif request.POST['task'] == 'mkdir':
        manager.mkdir(request.POST['dirname'])
    elif request.POST['task'] == 'rename':
        manager.rename_item(request.POST['item'], request.POST['new_item_name'])
    elif request.POST['task'] == 'chmod':
        manager.chmod_items(request.POST.getlist('items[]'), request.POST['permission'])
    elif request.POST['task'] == 'upload':
        remote_manager = FtpClientRemoteManager()
        if request.POST['type'] == 'remote':
            remote_manager.download_items(FtpClientLocalManager().get_dir(), request.POST.getlist('items[]'))
            response['dir_content'] = FtpClientLocalManager().get_dir_content()
        else:
            remote_manager.upload_items(request.POST.getlist('items[]'))
            response['dir_content'] = remote_manager.get_dir_content()
    elif request.POST['task'] == 'remove':
        manager.remove_items(request.POST.getlist('items[]'))

    if 'dir_content' not in response:
        response['dir_content'] = manager.get_dir_content()

    return HttpResponse(JSONEncoder().encode(response))


def connection_status(func):
    def check_connection(*args, **kwargs):
        try:
            args[0].get_connection().voidcmd("NOOP")
        except IOError:
            args[0].reconnect()
        return func(*args, **kwargs)

    return check_connection


class FtpClientLocalManager(object):
    _dir = None

    def __new__(cls, *args, **kwargs):
        if not hasattr(cls, 'instance'):
            cls.instance = super(FtpClientLocalManager, cls).__new__(cls)
            cls.instance._dir = os.path.join(os.getcwd(), 'ftp')
        return cls.instance

    def get_dir(self):
        return self._dir

    def set_dir(self, path):
        self._dir = path
        return True

    def mkdir(self, path):
        dir_full_path = os.path.join(self._dir, path)
        if not os.access(self._dir, os.W_OK) or os.path.exists(dir_full_path):
            return False

        os.mkdir(dir_full_path)
        return True

    def rename_item(self, item_name, new_item_name):
        try:
            os.rename(item_name, os.path.join(self._dir, new_item_name))
        except OSError:
            return False
        return True

    def chmod_items(self, items, permission):
        permission = int(permission, 8)
        for item in items:
            os.chmod(item, permission)
        return True

    def remove_dir(self, dirname):
        items = os.listdir(dirname)
        for item in items:
            item_path = os.path.join(dirname, item)
            if os.path.isfile(item_path):
                os.remove(item_path)
            else:
                self.remove_dir(item_path)
        os.rmdir(dirname)
        return True

    def remove_items(self, items):
        for item in items:
            item_type, item_path = item.split('@')
            if item_type == 'file':
                os.remove(item_path)
            else:
                self.remove_dir(item_path)
        return True

    def get_dir_content(self):
        dir_content = list()
        output = list()

        if os.path.exists(self._dir) and os.path.isdir(self._dir):
            dir_content = os.listdir(self._dir)

        for item in dir_content:
            item_path = os.path.join(self._dir, item)
            item_info = {
                'name': item,
                'info': '',
                'size': os.path.getsize(item_path),
                'perms': oct(stat.S_IMODE(os.stat(item_path).st_mode)),
                'type': '',
                'full_path': item_path,
            }

            if os.path.isdir(item_path):
                item_info['info'] = 'Catalog'
                item_info['type'] = 'catalog'
            else:
                item_ext = os.path.splitext(item_path)
                item_info['info'] = '%s-file' % item_ext[1] if len(item_ext) > 1 and item_ext[1] else 'File'
                item_info['type'] = 'file'

            output.append(item_info)

        output.sort(key=lambda i: i['name'] and i['type'])
        output.insert(0, {
            'name': '..',
            'info': '',
            'size': '',
            'perms': '',
            'type': 'catalog',
            'full_path': os.path.dirname(self._dir),
        })
        return output


class FtpClientRemoteManager(object):
    host = None
    user = None
    password = None
    _connection = None

    def __new__(cls, *args, **kwargs):
        if not hasattr(cls, 'instance'):
            cls.instance = super(FtpClientRemoteManager, cls).__new__(cls)
        return cls.instance

    def add_connection(self, host, port, user, password,mode):
        self.host = host
        self.user = user
        self.password = password
        self._connection = ftplib.FTP()
        self._connection.set_pasv(mode)  # 0主动模式 1 #被动模式
        # 连接的ftp sever和端口
        self._connection.connect(host, port)

        # 登录
        self._connection.login(user, password)

        # 打印欢迎信息
        print(self._connection.getwelcome())

        return self._connection

    def close_connection(self):
        self.host = None
        self.user = None
        self.password = None
        self._connection.close()
        self._connection = None

    def reconnect(self):
        self._connection = ftplib.FTP(self.host, self.user, self.password, timeout=5)

    def get_connection(self):
        return self._connection

    def upload_file(self, file_path):
        try:
            self._connection.storbinary("STOR %s" % os.path.basename(file_path), open(file_path, 'rb'))
        except ftplib.Error:
            return False
        return True

    def remove_dir(self, dirname):
        self._connection.cwd(dirname)
        dir_content = list()

        try:
            self._connection.retrlines('MLSD', dir_content.append)
        except ftplib.Error:
            return False

        for line in dir_content:
            items = line.split(';')
            item_name = items[-1].strip()
            item_type = items[0].split('=')[1]

            if item_name in ['.', '..']:
                continue

            if item_type == 'dir':
                self.remove_dir(item_name)
            elif item_type == 'file':
                try:
                    self._connection.delete(item_name)
                except ftplib.Error:
                    return False

        try:
            self._connection.cwd('..')
            self._connection.rmd(dirname)
        except ftplib.Error:
            return False
        return True

    @connection_status
    def get_dir(self):
        return self._connection.pwd()

    @connection_status
    def set_dir(self, path):
        try:
            self._connection.cwd(path)
        except ftplib.Error as e:
            return False
        return True

    @connection_status
    def get_dir_content(self):
        dir_content = list()
        output = list()

        try:
            # self._connection.retrlines('MLSD', dir_content.append)
            self._connection.dir(dir_content.append)
            self._connection.dir()
        except ftplib.Error as e:
            pass


        for line in dir_content:
            tokens = line.split(maxsplit=9)
            items = {}
            items['filename'] = tokens[-1]
            items['size'] = tokens[4]


            time_str = tokens[5] + " " + tokens[6] + " " + tokens[7]
            items['time'] = parser.parse(time_str)
            print(tokens)


            if tokens[-1].strip() == '.':
                continue

            if tokens[0].strip()[0]=='d':
                items['type'] = 'dir'
            else:
                items['type'] = 'file'


                #items[-1] = 'filename=%s' % items[-1].strip()
            #items = dict(map(lambda s: s.split('='), items))


            # item_info = {
            #     'name': items['filename'].strip(),
            #     'info': '',
            #     'size': items['sizd'] if 'sizd' in items else items['size'],
            #     'perms': items['UNIX.mode'],
            #     'type': items['type'],
            #     'full_path': None
            # }

            item_info = {
                'name': items['filename'].strip(),
                'info': '',
                'size': items['size'],
                'perms': '',
                'type': 'dir',
                'full_path': None
            }

            if items['filename'] in ['.', '..']:
                item_info['full_path'] = os.path.dirname(self._connection.pwd())
                item_info['type'] = 'catalog'
                item_info['size'] = ''
                item_info['perms'] = ''
            else:
                # item_info['full_path'] = os.path.join(self._connection.pwd(), items['filename'])
                # todo :改变此种连接方式，win下调试
                item_info['full_path'] = self._connection.pwd()+"/"+ items['filename']
                if items['type'] == 'dir':
                    item_info['info'] = 'Catalog'
                    item_info['type'] = 'catalog'
                else:
                    item_ext = os.path.splitext(items['filename'])
                    item_info['info'] = '%s-file' % item_ext[1] if len(item_ext) > 1 and item_ext[1] else 'File'
                    item_info['type'] = 'file'

            output.append(item_info)

        output.sort(key=lambda i: i['name'] and i['type'])
        return output

    @connection_status
    def mkdir(self, path):
        try:
            self._connection.mkd(path)
        except ftplib.Error:
            return False
        return True

    @connection_status
    def remove_items(self, items):
        try:
            for item in items:
                item_type, item_path = item.split('@')
                if item_type == 'file':
                    self._connection.delete(item_path)
                else:
                    self.remove_dir(item_path)
        except ftplib.Error:
            return False
        return True

    @connection_status
    def rename_item(self, item_name, new_item_name):
        item_name = os.path.basename(item_name)
        try:
            self._connection.rename(item_name, new_item_name)
        except ftplib.Error:
            return False
        return True

    @connection_status
    def chmod_items(self, items, permission):
        try:
            for item in items:
                self._connection.sendcmd('SITE CHMOD %s %s' % (permission, os.path.basename(item)))
        except ftplib.Error:
            return False

        return self.get_dir()


    @connection_status
    def download_items(self, local_dir_to, items):
        FTP_SERVER_TYPE = 1
        if not os.access(local_dir_to, os.W_OK):
            return False

        for item in items:
            item_type, item_name = item.split('@')
            item_name = os.path.basename(item_name)
            print(item_name)
            if item_type == 'file':
                f = open(os.path.join(local_dir_to, item_name), 'wb')
                try:
                    self._connection.retrbinary('RETR %s' % item_name, f.write)
                    f.close()
                except ftplib.Error as e:
                    # Remove empty file if `try` block raise error
                    os.remove(os.path.join(local_dir_to, item_name))
            elif item_type == 'catalog':
                item_path = os.path.join(local_dir_to, item_name)
                if not os.path.exists(item_path):
                    os.mkdir(item_path)

                dir_content = list()
                inner_items = list()

                try:
                    self._connection.cwd(item_name)
                    # 使用mlsd的方式
                    # self._connection.retrlines('MLSD', dir_content.append)
                    # 使用dir的方式
                    self._connection.dir(dir_content.append)
                except ftplib.Error:
                    continue

                for line in dir_content:
                    # 使用mlsd的方式
                    # items = line.split(';')
                    # item_name = items[-1].strip()
                    # item_type = items[0].split('=')[1]
                    # 使用dir的方式
                    tokens = line.split(maxsplit=3)
                    if len(tokens) < 4:
                        continue
                    if FTP_SERVER_TYPE == 0:
                        item_name = tokens[-1]
                        if tokens[0].strip()[0] == 'd':
                            item_type = 'dir'
                        else:
                            item_type = 'file'
                    else:
                        item_name = tokens[-1]
                        if '<DIR>' in line:
                            item_type = 'dir'
                        else:
                            item_type = 'file'

                    if item_type == 'dir':
                        inner_items.append('catalog@%s' % item_name)
                    elif item_type == 'file':
                        inner_items.append('file@%s' % item_name)

                self.download_items(item_path, inner_items)
                self._connection.cwd('..')

        return True

    @connection_status
    def upload_items(self, items):
        connection_root = self._connection.pwd()

        for item in items:
            if os.path.isdir(item):
                for cur_dir, child_dirs, files in os.walk(item):
                    # Create directory if not exists
                    # Set CWD
                    remote_dir = os.path.basename(cur_dir)
                    try:
                        self._connection.cwd(remote_dir)
                    except ftplib.error_perm:
                        try:
                            self._connection.mkd(remote_dir)
                        except ftplib.Error:
                            return False
                        else:
                            self._connection.cwd(remote_dir)

                    for f in files:
                        # open local file
                        file_path = os.path.join(cur_dir, f)
                        # create/open remote file
                        self.upload_file(file_path)

                self._connection.cwd(connection_root)
            elif os.path.isfile(item):
                self.upload_file(item)

        return self.get_dir()
