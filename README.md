# mautrix-wechat
A Matrix-Wechat puppeting bridge, based on https://github.com/ChisBread/wechat-box

# Usage

## Run wechat-service

### Run bridge bot together with wechat box

If you only have one wechat account to bridge, it's recommended to run the bridge bot with wechat box in one docker container. First let's create a sample config
```shell
mkdir -p mautrix-wechat && cd mautrix-wechat
wget https://raw.githubusercontent.com/LeiShi1313/mautrix-wechat/main/mautrix_wechat/example-config.yaml -o config.yaml
```
then edit the config to suit your homeserver, you will need to change the admin account in `wechat.boxes` section, and geenrally you don't need maunal login option so remove the other demonstration box config. Now we start the wechat box:

```shell
docker run -d --name mautrix-wechat-box -v $(pwd):/data -p 8080:8080 -p 29380:29380  leishi1313/mautrix-wechat-box
docker exec -ti mautrix-wechat-box python -m mautrix_wechat -g
```
When the box is up, open `localhost:8080/vnc.html` to continue with the login process. Then copy the generated `registration.yaml` to your homeserver config, and restart your homeserver.

### Run bridge bot and wecaht box seperatly 

#### Run wechat box

Firstly, you need to have one or multiple wechat box running, to do that:
```shell
docker run -d --name wechat-service --rm  \
    -e HOOK_PROC_NAME=WeChat \
    -e HOOK_DLL=auto.dll \
    -e TARGET_AUTO_RESTART="yes" \
    -e INJ_CONDITION="[ \"\`sudo netstat -tunlp | grep 5555\`\" != '' ] && exit 0 ; sleep 5 ; curl 'http://127.0.0.1:8680/hi' 2>/dev/null | grep -P 'code.:0'" \
    -e TARGET_CMD=wechat-start \
    -v "$(pwd)/WeChat Files:/home/app/WeChat Files" \
    -p 8080:8080 -p 5555:5555 -p 5900:5900 \
    --add-host=dldir1.qq.com:127.0.0.1 \
    chisbread/wechat-service:latest
```

And then, go to `localhost:8080/vnc.html` to finish the login step.

You can start as many wechat boxes as you want.

#### Run mautrix-wechat

```shell
mkdir mautrix-wechat && cd mautrix-wechat
wget https://raw.githubusercontent.com/LeiShi1313/mautrix-wechat/main/mautrix_wechat/example-config.yaml -o config.yaml
docker run -d --name mautrix-wechat  -v $(pwd):/data leishi1313/mautrix-wechat 
docker exec -ti mautrix-wechat python -m mautrix_wechat -g
```

Now copy the generated `registration.yaml` to your homeserver config, and restart your homeserver.


# TODO:

### WeChat box
- [ ] Auto reconnect

### WeChat -> Matrix
- [x] 接收微信文本消息
- [x] 接收微信图片消息 
- [ ] 接收微信引用消息
  - [ ] 接收链接
  - [x] 就收Quote消息

### Matrix -> WeChat
- [x] 发送文本消息
- [ ] 发送图片信息（可能无法做到）
- [ ] 发送at消息
- [ ] 从matrix端发送DM/群消息（matrix room未创建）

### Docker
- [ ] python not receiving SIGINT