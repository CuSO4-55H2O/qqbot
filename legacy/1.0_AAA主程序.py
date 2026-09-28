from 输出 import *
from 输入 import *
from 定义 import *
from 骰子 import dice
from 管理员 import master
from 读取文件 import *
from 漂流瓶 import *
from 唐诗 import *
from 乌合之众 import read_pro,rabble
from 斗地主 import ddz,ddz_1
from 抓取视频 import video
#from 文字转图片 import generate_image
import queue
import copy
import time
import datetime
import random
import os
import json
import threading
#generate_image()
self =1000000001
rep=defi=[]
blacklist=read_black()
content = read_poems('../文档/唐诗1000.txt')
poems_data = [process_poem(poem) for poem in extract_poems(content)]
placex=os.path.dirname(os.getcwd())
place = "file:///"+placex+"\图片"
place1 = "file:///"+placex+"\扑克牌"
place2 = "file:///"+placex+"\capoo"
place3 = "file:///"+placex+"\hsd笑话"
cap = os.listdir(placex+"/capoo")
hsd = os.listdir(placex+"/hsd笑话")
op = read_op()
defined = define(0, 0, 0,0)
images=read_image()
cnt=plp_ini()
options=read_options()
administrators=read_administrators()
super_=1000000002
players0, whzz,pro,meo,group0,f=read_pro()
stage,group1,players1,cards,remain,turn,k,times,dz=ddz_1()
while True:
    try:
        rev = rev_msg()
        if rev == None:
            continue
    except:
        continue
    if rev["post_type"] == "meta_event":
        now =datetime.datetime.now()
        if now.hour==12 and now.minute==0 and 5>now.second>0:
            send_msg({'msg_type': 'group', 'number': 1000000003,'msg': "ljqm"})

    elif rev["post_type"] == "message" and rev["raw_message"]!="":
        if rev["message_type"] == "private":  # 私聊

            qq = rev['sender']['user_id']
            mes=rev['raw_message']

            if qq in blacklist:
                text='你已被加入黑名单，请联系管理员\n'+'超级管理员：\n'+str(super_)+'\n管理员：\n'
                for i in administrators:
                    text = text+str(i)+"\n"
                send_msg({'msg_type': 'private', 'number': qq, 'msg': text})
                continue

            if len(mes)>4 and mes[:4]=='联系管理员':
                text=qq+' '+rev['nickname']+' '+mes[4:]
                send_msg({'msg_type': 'private', 'number': super_, 'msg': text})

            if options["image"] == 1 or mes in ["砰砰机器人帮助", "管理员帮助", '帮助']:
                if mes in images:
                    temp = images[mes]
                    find_image1(mes, qq, temp, place)
                    continue
                elif mes == "图片列表":
                    text = "图片列表："+"，".join(images)
                    send_msg(
                        {'msg_type': 'private', 'number': qq, 'msg': text})
                    continue

            if len(mes) > 1 and mes[0] == "1" and (qq == super_ or qq in administrators):
                if len(mes)>4:
                    group=0
                    o = master(mes[1:], group, qq, options,
                               administrators, super_)
                    if o != 0:
                        send_msg(
                            {'msg_type': 'private', 'number': qq, 'msg': '已执行'})
                    if o == 1:
                        defined = define(0, 0, 0, 0)
                    elif o == 2:
                        options = read_options()
                    elif o == 3:
                        players0, whzz, pro, meo, group1, f = read_pro()
                    elif o == 4:
                        cnt = 0
                    elif o == 5:
                        administrators = read_administrators()
                    elif o == 6:
                        stage, group1, players1, cards, remain, turn, k, times, dz = ddz_1()
                    elif o==7:
                        blacklist = read_black()
                
            if options["plp"] == 1:
                if len(mes)>=4 and mes[1:4] == "漂流瓶":
                    cnt=plp1(mes,qq)
                elif mes == "漂流瓶海":
                    send_msg({'msg_type': 'private', 'number': qq,
                              'msg': "漂流瓶海里有"+str(cnt)+"个漂流瓶"})

            if options["draw_card"]==1:
                if mes== "抽一张牌":
                    text = "[CQ:image,file="+place1+"\\"+str(random.randint(1,52))+".png]"
                    send_msg({'msg_type': 'private', 'number': qq,
                              'msg':text })
            
            if options["whzz"] == 1:
                if mes in ["A", "a", "B", "b", "C", "c","D","d"]:
                    rev1=copy.deepcopy(rev)
                    players0, whzz, pro, meo, group0, f=rabble(players0, whzz, pro, group0, rev, f, meo)

            if options["capoo"]==1:
                if mes in ["咖波","capoo"]:
                    ran = random.choice(cap)
                    text = "[CQ:image,file="+place2+"\\"+ran+"]"
                    send_msg({'msg_type': 'private', 'number': qq,'msg': text})
            
            if options["op"]==1:
                if rev['raw_message']=="op段子":
                    text = random.choice(op)
                    send_msg({'msg_type': 'private', 'number': qq,'msg': text})
                            
        elif rev["message_type"] == "group":  # 群聊

            group = rev['group_id']
            mes = rev['raw_message']
            qq = rev['sender']['user_id']
            
            if qq in blacklist:
                continue

            if mes == "查看设置":
                text="设置：\n"
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
                continue


            if options["op"]==1:
                if rev['raw_message']=="op段子":
                    text = random.choice(op)
                    send_msg({'msg_type': 'group', 'number': group,'msg': text})
                    continue
            
            if options["time"]==1:
                if mes=="时间":
                    today = datetime.datetime.now()
                    date_string = today.strftime("%Y-%m-%d %H:%M:%S")
                    send_msg({'msg_type': 'group', 'number': group,'msg': date_string})
                    continue

            if options["image"] == 1 or mes in ["砰砰机器人帮助","管理员帮助",'帮助']:
                if mes in images:
                    temp=images[mes]
                    find_image(mes,group,temp,place)
                    continue
                elif mes == "图片列表":
                    text="图片列表："+"，".join(images)
                    send_msg({'msg_type': 'group', 'number': group,'msg': text})
                    continue

            if options["dice"] == 1:
                if mes[0] in ["d", "D"] :
                    dice(mes,group,qq)
                    continue

            if options["capoo"] == 1:
                if mes in ["咖波","capoo"]:
                    ran = random.choice(cap)
                    text = "[CQ:image,file="+place2+"\\"+ran+"]"
                    send_msg({'msg_type': 'group', 'number': group,'msg': text})
                    cap.remove(ran)
                    if len(cap)==0:
                        cap = os.listdir(placex+"/capoo")
                    continue

            if options["hsd"] == 1:
                if mes =='hsd笑话':
                    ran = random.choice(hsd)
                    text = "[CQ:image,file="+place3+"\\"+ran+"]"
                    send_msg(
                        {'msg_type': 'group', 'number': group, 'msg': text})
                    hsd.remove(ran)
                    if len(hsd)==0:
                        hsd = os.listdir(placex+"/hsd笑话")
                    continue

            if options["plp"] == 1:
                if mes[1:4]=="漂流瓶":
                    cnt=plp(mes,group,qq)
                    continue
                elif mes == "漂流瓶海":
                    send_msg({'msg_type': 'group', 'number': group,'msg': "漂流瓶海里有"+str(cnt)+"个漂流瓶"})
                    continue

            if options["whzz"] == 1:
                if mes in ["开始游戏","加入游戏","退出游戏"]:
                    rev1=copy.deepcopy(rev)
                    players0, whzz, pro, meo, group0, f = rabble(players0, whzz, pro, group0, rev1, f, meo)
                    continue

            if options["ddz"] == 1:
                if mes in ["上桌","下桌","不叫","不出","开始游戏1"] or mes[0] in ["叫","出"]:
                    rev1=copy.deepcopy(rev)
                    stage,group1,players1,cards,remain,turn,k,times,dz=ddz(stage,group1,rev1,players1,cards,remain,turn,k,times,dz)
                    continue

            if options["video"] == 1:
                if mes[:2]=="BV" or mes[:2]=="av":
                    try:
                        v=mes
                        video(v)
                        text = "[CQ:video,file=file:///"+placex+"\视频\一.mp4]"
                        send_msg({'msg_type': 'group', 'number': group, 'msg': text})
                        continue
                    except:
                        continue

            if options["draw_card"] == 1:
                if mes== "抽一张牌":
                    text = "[CQ:image,file="+place1+"\\"+str(random.randint(1,52))+".png]"
                    send_msg({'msg_type': 'group', 'number': group,'msg':text})
                    continue

            if options["poem"]==1:
                if mes[:2] == "唐诗":
                    mes=mes[2:]
                    poem(mes,group,content,poems_data)
                    continue

            if options["repeat"]==1:
                if mes[-1]=="喵":
                    if len(rep)>=3:
                        del rep[0]
                    if mes not in rep:
                        send_msg({'msg_type': 'group', 'number': group,'msg':mes})
                    rep.append(mes)
                    continue

            if len(mes)>1 and mes[0] == "1" and (qq == super_ or qq in administrators):
                if len(mes)>=4:
                    o = master(mes[1:], group, qq, options,
                               administrators, super_)
                    if o!=0:
                        send_msg({'msg_type': 'group', 'number': group,'msg': '已执行'})
                        f2=1
                    if o==1:
                        defined = define(0, 0, 0,0)
                    elif o==2:
                        options = read_options()
                    elif o==3:
                        players0, whzz, pro, meo, group1, f=read_pro()
                    elif o==4:
                        cnt=0
                    elif o==5:
                        administrators=read_administrators()
                    elif o==6:
                        stage,group1,players1,cards,remain,turn,k,times,dz=ddz_1()
                    elif o==7:
                        blacklist = read_black()


            if options["define"] == 1:
                if rev['raw_message'][:2] == "定义" and "=" in rev['raw_message']:
                    defined=define(rev,group,administrators,super_)
                elif rev['raw_message']== "定义列表":
                    text=""
                    for i in defined:
                        text=text+i+"="+defined[i]+"\n"
                    send_msg({'msg_type': 'group', 'number': group,'msg': text})
                elif mes[:5] == "1删除定义" and (rev['sender']['user_id'] == super_ or rev['sender']['user_id'] in administrators):
                    if mes[5:] in defined:
                        del defined[mes[5:]]
                        define_del(defined, group)
                elif mes in defined:
                    if len(defi)>=3:
                        del defi[0]
                    if mes not in defi:
                        send_msg({'msg_type': 'group', 'number': group,'msg': defined[mes]})
                    defi.append(mes)
        else:
            continue
            
    elif rev['post_type']=='notice':
        if options['poke']==1:
            if rev['notice_type']== 'notify' and rev['sub_type']=='poke' and 'group_id' in rev:
                a=rev['sender_id']
                b=rev['target_id']
                group = rev['group_id']
                if (b==super_ or b in administrators or b==self) and a!=self:
                    qq=a
                    send_msg({'msg_type': 'group', 'number': group, 'msg': f"[CQ:poke,qq={qq}]"})
                elif a==super_ or a in administrators:
                    qq=b
                    send_msg({'msg_type': 'group', 'number': group, 'msg': f"[CQ:poke,qq={qq}]"})
        
        if options['recall']==1:
            if rev['notice_type']=='group_recall':
                group=rev['group_id']
                order=rev['message_id']
                recall(group,order)

    elif rev['post_type'] == 'request':
        if options['friends']==1:
            if rev['request_type']=='friend':
                make_friends(rev['flag'])
            elif rev['request_type'] == 'group':
                if rev['sub_type']=='invite':
                    enter_group(rev[flag])

    else:
        continue