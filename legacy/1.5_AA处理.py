import os

from 乌合之众 import read_pro, rabble
#from 文字转图片 import generate_image
from 作品展 import work_show
from 唐诗 import *
from 定义 import *
from 斗地主 import ddz, ddz_1
from 漂流瓶 import *
from 管理员 import master
from 读取文件 import *
from 骰子 import dice
from 输出 import *
from 记录 import *
from 深度求索 import *
from roulette.roulette import Manager

#generate_image()
rep=[]
define_list={}
blacklist=read_blacklist()
hsd = os.listdir(os.path.dirname(os.getcwd())+r"/hsd笑话")
hsd.remove('disabled')
hsd.remove('轮换')
op = read_op()
defined = defines()
images=read_image()
cnt_1=plp_ini()
options=read_options()
administrators=read_administrators()
super_=1000000002
self=read_id()
dic2=read_pro()
manager=Manager()
def handle(rev):
    global options,dic1,dic2,administrators,cnt_1,images,defined,op,hsd,blacklist
    global define_list,rep,dic
    x = 0
    if rev['post_type'] == 'message':
        if rev["message_type"] == "private":  # 私聊
            qq = int(rev['sender']['user_id'])
            mes=rev['raw_message']
            nickname = rev['sender']['nickname']
            if qq==self:
                x=1
            if mes=='':
                x=1
            if qq in blacklist:
                text='你已被加入黑名单，请联系管理员\n'+'超级管理员：\n'+str(super_)+'\n管理员：\n'
                for i in administrators:
                    text = text+str(i)+"\n"
                send_msg({'msg_type': 'private', 'number': qq, 'msg': text})
                x=1

            if len(mes)>4 and mes[:5]=='联系管理员' and x==0:
                text=str(qq)+' '+nickname+' '+mes[5:]
                send_msg({'msg_type': 'private', 'number': super_, 'msg': text})
                send_msg({'msg_type': 'private', 'number': qq, 'msg': '已发送'})
                x=1
            if mes=='1000':
                headers = {'Content-Type': 'application/json'}
                data = json.dumps({"group_id":1000000004, "messages": [
    {'type':'node','data':{
        'id':1000000005
    }
    }]})
                response = requests.post(
                    net() + '/send_group_forward_msg', data=data, headers=headers)
                print("发送")

            if mes=='100':
                f = open('../json/记录1.json', 'r')
                i = json.load(f)
                f.close()
                t=''
                for j in i:
                    j=re.sub(r'\[.*?\]', '',j)
                    t+=j+'\n'
                send_msg({'msg_type': 'group', 'number': 1000000004,
                          'msg': t})

            '''if options["image"] == 1 and x==0 or mes in ["砰砰机器人帮助", "管理员帮助", '帮助']:
                if mes in images:
                    temp = images[mes]
                    find_image1(mes, qq, temp, place)
                    x=1
                elif mes == "图片列表":
                    text = "图片列表："
                    for i in images:
                        if '帮助' not in i:
                            text+=i+'，'
                    text=text[:-1]
                    send_msg(
                        {'msg_type': 'private', 'number': qq, 'msg': text})
                    x=1
            '''

            if options["show"] == 1 and x==0:
                if len(mes) >= 2 and mes[:2] in ['展出', '上传', '删除', '评论']:
                    work_show(mes, qq, 0,  nickname)
                    x=1

            if len(mes) > 1 and (qq == super_ or qq in administrators):
                if len(mes)>4:
                    group=0
                    o = master(mes, group, qq, options,
                            administrators, super_)
                    if o != 0:
                        send_msg(
                            {'msg_type': 'private', 'number': qq, 'msg': '已执行'})
                        x=1
                    if o == 1:
                        defined = define(0, 0, 0, 0,qq)
                    elif o == 2:
                        options = read_options()
                    elif o == 3:
                        dic2= read_pro()
                    elif o == 4:
                        cnt_1= 0
                    elif o == 5:
                        administrators = read_administrators()
                    elif o==7:
                        blacklist = read_blacklist()

            if options["plp"] == 1 and x==0:
                if len(mes)>=4 and mes[1:4] == "漂流瓶":
                    cnt_1=plp(rev)
                    x=1
                elif mes == "漂流瓶海":
                    send_msg({'msg_type': 'private', 'number': qq,
                                'msg': "漂流瓶海里有"+str(cnt_1)+"个漂流瓶"})
                    x=1

            if options["whzz"] == 1 and x==0:
                if mes in ["A", "a", "B", "b", "C", "c","D","d"]:
                    dic2=rabble(dic2,rev)
                    x=1

            if options["capoo"]==1 and x==0:
                if mes in ["咖波","capoo"]:
                    ran = random.choice(os.listdir(os.path.dirname(os.getcwd())+r"/capoo"))
                    text = "[CQ:image,file=file:///"+os.path.dirname(os.getcwd())+r"\capoo"+"\\"+ran+"]"
                    send_msg({'msg_type': 'private', 'number': qq,'msg': text})
                    x=1

            if options["op"]==1 and x==0:
                if mes=="op段子":
                    text = random.choice(op)
                    send_msg({'msg_type': 'private', 'number': qq,'msg': text})
                    x=1

        elif rev["message_type"] == "group":  # 群聊
            group = rev['group_id']
            qq = int(rev['sender']['user_id'])
            nickname=rev['sender']['nickname']
            mes =rev['message']
            if mes=='':
                x=1
            if '~' in mes:
                x=1
            if qq in blacklist:
                x=1
            if qq==self:
                x=1

            if mes == "查看设置":
                text = "设置：\n"
                for i in options:
                    text=text+i+"="+str(options[i])+"\n"
                text=text+"管理员：\n"
                for i in administrators:
                    text=text+str(i)+"\n"
                text=text+"超级管理员："+"\n"+str(super_)
                text=text+'\n黑名单：\n'
                for i in blacklist:
                    text=text+str(i)+"\n"
                send_msg({'msg_type': 'group', 'number': group, 'msg': text})
                x=1

            if mes == "查看铸币":
                check(group)
                x=1

            if mes=='暗锅题数':
                blackpot(group)
                x=1

            if options['deepseek']==1 and x==0:
                if mes[0]=='%' and len(mes)>2:
                    text=deepseek(mes[1:],qq)
                    send_msg(
                        {'msg_type': 'group', 'number': group, 'msg': text})
                    x=1
                elif mes=='查看余额':
                    text =balance()
                    send_msg(
                        {'msg_type': 'group', 'number': group, 'msg': text})
                    x = 1

            if options['record']==1 and x==0:
                if len(mes)>2:
                    if mes[:3]=='记录 ':
                        i={'name':nickname,'uin':qq,'content':mes[3:],'time':rev['time']}
                        record(i,group)
                        x=1
                    elif len(mes)>4 and mes[:4]=='删除记录':
                        a=mes[4:]
                        delete_record(a,group,qq,super_,administrators)
                    elif '[CQ:reply' in mes:
                        m=re.sub(r'\[.*?\]', '', mes)
                        m=m.replace(' ','')
                        if m=='记录':
                            match = re.search(r'CQ:reply,id=(\d+)', mes)
                            id=match.group(1)
                            record_id(id,blacklist)
                            x=1
                    elif mes=='查看记录':
                        read_record(group,1,0)
                        x=1
                    elif mes=='记录查看':
                        read_record(group, 2,0)
                        x=1
                    elif mes =='查看历史记录':
                        read_record(group, 4, 0)
                        x=1
                    elif len(mes)>4 and mes[:4]=='查看记录':
                        read_record(group, 3,mes[4:])
                        x=1

            '''
            if options["wheel"] == 1 and x == 0:
                instructions=['加入轮盘','退出轮盘','开始轮盘','向自己开枪','向对手开枪','向自己射击','向对手射击','苦肉','向靶子射击',
                              '向靶子开枪','跳过回合']
                if mes in instructions or (len(mes) >= 2 and mes[:2] in ['使用','模式','重置']):
                    if group not in dic:
                        dic[group]=ini_wheel()
                    dic[group]=wheel(dic[group],rev)
                    print(dic)
                    x = 1
                elif mes=='轮盘帮助':
                    wheel_help(group)
                    x=1
                elif mes=='轮盘历史记录':
                    wheel_hist(group)
                    x=1
                elif mes=='轮盘胜率':
                    wheel_rate(group)
                    x=1
            '''
            if options["wheel"] == 1 and x == 0:
                handler = manager.get_handler(group)
                replies = handler.process(qq, mes, nickname)
                private_msgs = handler.fetch_flush_private()
                if replies or private_msgs:
                    for text in replies:
                        send_msg({'msg_type':'group','number':group
                                  ,'msg':text})
                    for target_user_id, private_text in private_msgs:
                        send_msg({'msg_type': 'private', 'number': target_user_id, 'msg': private_text})
                    x=1
                if mes == '轮盘帮助':
                    wheel_help(group)
                    x = 1


            if options["show"] == 1 and x == 0:
                if len(mes) >= 2 and (mes[:2] in ['展出', '上传'] or mes[:3] in ['删除#', '评论#']):
                    work_show(mes,qq,group,nickname)
                    x=1

            '''if options["video"] == 1 and x == 0:
                if mes[:2] == "BV" or mes[:2] == "av":
                    v = mes
                    video(v)
                    text = "[CQ:video,file=file:///"+os.path.dirname(os.getcwd())+"\视频\一.mp4]"
                    send_msg(
                        {'msg_type': 'group', 'number': group, 'msg': text})
                    x=1
            '''

            if options["op"] == 1 and x == 0:
                if mes == "op段子":
                    text = random.choice(op)
                    send_msg({'msg_type': 'group', 'number': group,'msg': text})
                    x=1

            if options["image"] == 1 and x == 0 or mes in ["砰砰机器人帮助", "管理员帮助", '帮助',f'[CQ:at,qq={self},name={mynickname}]']:
                if mes==f'[CQ:at,qq={self},name={mynickname}]':
                    mes='帮助'
                m = re.sub(r'\[.*?\]', '', mes)
                m = m.replace(' ', '')
                if m in images:
                    mes=m
                    temp=images[mes]
                    find_image(mes,group,temp,"file:///"+os.path.dirname(os.getcwd())+r"\图片")
                    x=1
                elif mes == "图片列表":
                    text = "图片列表："
                    for i in images:
                        if '帮助' not in i:
                            text += i + '，'
                    text = text[:-1]
                    send_msg(
                        {'msg_type': 'group', 'number': group, 'msg': text})
                    x = 1

            if options["dice"] == 1 and x == 0:
                if mes[0] in ["d", "D"]:
                    dice(mes,group,qq)
                    x=1

            if options["capoo"] == 1 and x == 0:
                if mes in ["咖波", "capoo"]:
                    ran = random.choice(os.listdir(os.path.dirname(os.getcwd())+r"/capoo"))
                    text = "[CQ:image,file=file:///"+os.path.dirname(os.getcwd())+r"\capoo"+"\\"+ran+"]"
                    send_msg({'msg_type': 'group', 'number': group,'msg': text})
                    x=1

            if options["hsd"] == 1 and x == 0:
                if mes == 'hsd笑话' or mes=='HSD笑话':
                    ran = random.choice(hsd)
                    text = "[CQ:image,file=file:///"+os.path.dirname(os.getcwd())+r"\hsd笑话"+"\\"+ran+"]"
                    send_msg(
                        {'msg_type': 'group', 'number': group, 'msg': text})
                    hsd.remove(ran)
                    if len(hsd)==0:
                        hsd = os.listdir(os.path.dirname(os.getcwd())+"/hsd笑话")
                    x=1

            if options["plp"] == 1 and x == 0:
                if mes[1:4] == "漂流瓶":
                    cnt_1=plp(rev)
                    x=1
                elif mes == "漂流瓶海":
                    send_msg({'msg_type': 'group', 'number': group,'msg': "漂流瓶海里有"+str(cnt_1)+"个漂流瓶"})
                    x=1

            if options["whzz"] == 1 and x == 0:
                if mes in ["开始乌合之众", "加入乌合之众", "退出乌合之众",'提醒'] or mes=='盲选' and qq==super_:
                    dic2=rabble(dic2,rev)
                    x=1
                elif mes=='查看题库':
                    show_pro(group)

            if options["poem"] == 1 and x == 0:
                if mes[:2] == "唐诗":
                    mes = mes[2:]
                    poem(mes,group)
                    x=1

            if len(mes)>=4 and (qq in administrators or qq==super_):
                o = master(mes, group, qq, options,
                        administrators, super_)
                if o!=0:
                    send_msg({'msg_type': 'group', 'number': group,'msg': '已执行'})
                    x=1
                if o==1:
                    defined = define(0, 0, 0,0,qq)
                elif o==2:
                    options = read_options()
                elif o==3:
                    dic2=read_pro()
                elif o==4:
                    cnt_1=0
                elif o==5:
                    administrators=read_administrators()
                elif o==7:
                    blacklist = read_blacklist()

            if options["repeat"] == 1 and x == 0:
                if mes[-1] == "喵":
                    if len(rep)>=3:
                        del rep[0]
                    if mes not in rep:
                        send_msg({'msg_type': 'group', 'number': group,'msg':mes})
                    rep.append(mes)
                    x=1

            if options["define"] == 1 and x == 0:
                if mes[:2] == "定义" and "=" in mes:
                    defined = define(
                        mes, group, administrators, super_, qq)
                elif mes == "查看定义":
                    text = ""
                    for i in defined:
                        if '[CQ:at' not in defined[i]:
                            text = text + i + "=" + defined[i] + "\n"
                    send_msg({'msg_type': 'group', 'number': group, 'msg': text})
                elif len(mes) >= 5 and mes[:4] == '删除定义' and (qq == super_ or qq in administrators):
                    if mes[4:] in defined:
                        del defined[mes[4:]]
                        define_del(defined, group)
                m = re.sub(r'\[.*?\]', '', mes)
                m = m.replace(' ', '')
                if m in defined:
                    mes=m
                    if group not in define_list:
                        define_list[group] = {}
                    if mes not in define_list[group]:
                        define_list[group][mes] = 0
                    if time.time() - define_list[group][mes] > 10:
                        send_msg({'msg_type': 'group', 'number': group, 'msg': defined[mes]})
                        define_list[group][mes] = time.time()

    if rev['post_type']=='notice':
        if rev['notice_type']=='notify':
            if rev['sub_type']=='poke' and rev['target_id']==self and 'group_id' in rev:
                group = rev['group_id']
                qq = int(rev['user_id'])
                group_poke(qq, group)