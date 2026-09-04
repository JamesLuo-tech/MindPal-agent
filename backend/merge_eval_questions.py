"""把人工审核后的 TestsetGenerator 候选题、两篇之前零覆盖文档的手写题、
以及重新设计过的真负例，合并进正式的 eval_questions.json。

人工审核这一步做了什么（不是简单地全部塞进去）：
  1. 丢掉 4 条候选题：#10（问法太干、答案是原文碎片，不像真实用户提问）、
     #15（两个不相关的问题硬凑在一起）、#24 和 #26（考试式书面语，"请结合...
     说明为什么...具有其特定的科学依据"这种没有真实用户会这样问）
  2. 改写 #29 的 ground_truth：原文断言"糖尿病和抑郁症确实可能同时存在"，
     但知识库原文只是拿糖尿病做类比说明抑郁症是生理性疾病，并没有讨论两者
     共病关系——这是生成时的轻微过度引申，已经改成如实说明知识库没有回答
     这一部分，同时更多引用问题里描述的具体症状（PHQ-9 相关内容），比编造
     一个资料里没有的结论更诚实。
"""
import json
from pathlib import Path

ORIGINAL_FILE = Path("app/knowledge/eval_questions.json")
CANDIDATES_FILE = Path("app/knowledge/eval_questions_candidates.json")
OUT_FILE = Path("app/knowledge/eval_questions.json")

DROP_INDICES = {10, 15, 24, 26}  # 1-based，对应候选集里被剔除的 4 条

# #29（1-based）的 ground_truth 过度引申，替换成如实说明知识库未覆盖共病关系的版本
FIXED_29_GROUND_TRUTH = (
    "根据资料，抑郁症和糖尿病一样，都是生理性疾病——抑郁是大脑神经递质失衡，"
    "糖尿病是胰岛素分泌异常，不是意志力不够或矫情。资料里没有直接讨论糖尿病会不会"
    "让人更容易得抑郁症，但你描述的这些情况（持续两周以上情绪低落、对以前喜欢的事"
    "失去兴趣、睡眠和食欲变化、精力差、注意力难集中，甚至有不想活的念头）确实符合"
    "抑郁症的核心症状。可以用 PHQ-9 量表（手机搜一下，免费的）做初步筛查，得分只是"
    "参考，不是诊断，但能帮你判断是否需要就医。你没有义务告诉任何人，可以选择信任"
    "的人慢慢说——抑郁症很常见，是可以治疗的。"
)

NEW_HAND_WRITTEN = [
    {
        "topic": "breakup",
        "question": "分手快一个月了，还是老忍不住翻他朋友圈，这样正常吗",
        "ground_truth": "失恋的痛苦是真实的，脑成像研究显示失恋激活的脑区和身体疼痛有重叠，不是\"想太多\"。反复翻对方社交媒体、聊天记录，每次都是重新揭开伤口，会让恢复变慢，可以试着减少这种触发点。同时可以允许自己难过、找一个信任的人说说话、让身体动起来（散步、运动，换个环境）。没有固定的\"多久能好\"，关系越长往往恢复越慢是正常的，一般最难受的高峰会在几周内过去，完全走出来可能需要几个月。但如果两周以上睡眠和饮食严重受影响，或者有伤害自己的念头，需要找专业的人聊聊。",
    },
    {
        "topic": "exam_anxiety",
        "question": "还有三天就考试了，一看书就心慌根本看不进去，怎么办",
        "ground_truth": "考试焦虑是身体把考试识别成威胁、启动了战逃模式的真实反应，所以会心跳加速、注意力散。复习期间可以把任务拆得极小（比如\"看第三章第一小节，20分钟\"而不是\"背完第三章\"），用番茄钟（25分钟专注+5分钟休息）。考前一天建议停止复习，睡个好觉比临时抱佛脚更有用。考试当天紧张时可以用 4-7-8 呼吸法（吸气4秒、屏息7秒、呼气8秒）让身体平静下来，脑子空白时先做会的题，不要卡在一道题上。适度焦虑其实是动力，问题只是焦虑超过了自己能处理的程度，如果长期严重影响，可以和学校心理中心聊聊，这是很常见的事。",
    },
    {
        # depression_youth 唯一的覆盖来自被剔除的候选题 #24（问法太学术），这里单独补一条
        # 口语化的，正好也是候选集里完全没出现过的"家长视角"提问
        "topic": "depression_youth",
        "question": "我儿子最近总是发脾气，一说他就摔东西，是不是青春期叛逆啊",
        "ground_truth": "青少年抑郁很容易被误认成\"青春期叛逆\"，跟成人抑郁表现不太一样——青少年更多是烦躁、易怒（动不动发脾气、容易崩溃），而不是像成人那样情绪低落；还常伴随头痛、肚子痛、总是疲惫这类检查不出问题的身体症状，回避上学、成绩下滑、社交退缩（不想出门、把自己关房间里）、对未来失去信心。青少年抑郁不会自然消失，越早干预效果越好，\"成绩好就没问题\"也不成立，高压学业环境本身就是诱因。作为家长，建议先不要评判，先问\"你最近怎么了\"，然后真的听完——能被听见，比给建议重要得多。",
    },
]

# 替换原来的 fallback_test 组——原来 5 条里有 3 条（正念/考试焦虑/失恋）现在知识库
# 其实已经覆盖了，不再是真正的"知识库没有"场景。新的一组分两类：
#   - 心理健康相关但知识库确实没有专门文档的话题（PTSD、强迫症），测的是"话题沾边
#     但检索分数不该被拉到阈值以上，不能硬凑本地文档回答"
#   - 完全无关的话题，测最基本的兜底（不该被路由到 lookup，或者 lookup 该直接查网络）
OUT_OF_DOMAIN = [
    {
        "topic": "out_of_domain",
        "question": "双相情感障碍和抑郁症有什么区别",
        "ground_truth": "知识库里没有专门讲双相情感障碍的资料，不应该照抑郁症的内容硬答。双相情感障碍有躁狂和抑郁两个阶段交替出现，而抑郁症只有持续低落情绪，两者的治疗方案和用药不同，需要专业诊断区分，应该走实时搜索或如实告知知识库未覆盖，而不是从抑郁症资料里拼凑答案。",
    },
    {
        "topic": "out_of_domain",
        "question": "创伤后应激障碍要怎么自己调节",
        "ground_truth": "知识库里没有专门讲 PTSD（创伤后应激障碍）的资料。虽然和焦虑、抑郁话题相邻，但不应该把知识库里关于焦虑或抑郁的应对方法直接套用成 PTSD 的答案，应该走实时搜索或如实告知知识库未覆盖这个话题。",
    },
    {
        "topic": "out_of_domain",
        "question": "总是反复检查门有没有锁好，锁好了还是不放心，是不是强迫症",
        "ground_truth": "知识库里没有专门讲强迫症（OCD）的资料。这个话题和焦虑相邻但不等同，不应该把知识库里关于焦虑发作的应对方法（呼吸法、接地技巧）当成强迫症的专业建议直接给出，应该走实时搜索或如实告知知识库未覆盖，并建议咨询专业人士。",
    },
    {
        "topic": "out_of_domain",
        "question": "我家猫最近一直不吃东西，是不是生病了",
        "ground_truth": "这个问题和心理健康知识库完全无关，属于宠物健康问题。系统不应该从心理健康知识库里检索任何内容来回答，应该识别这是知识库范围外的问题，走实时搜索或如实告知无法回答，不能编造内容。",
    },
    {
        "topic": "out_of_domain",
        "question": "电脑蓝屏了要怎么修",
        "ground_truth": "这个问题和心理健康知识库完全无关，属于电脑故障排查问题。系统不应该从心理健康知识库里检索任何内容来回答，应该识别这是知识库范围外的问题，走实时搜索或如实告知无法回答，不能编造内容。",
    },
]


def main():
    original = json.loads(ORIGINAL_FILE.read_text(encoding="utf-8"))
    candidates = json.loads(CANDIDATES_FILE.read_text(encoding="utf-8"))

    kept_hand_written = original[:15]  # sleep/anxiety/medication/family/cbt/self_help/psychiatrist，全部保留

    kept_candidates = []
    for i, c in enumerate(candidates, 1):
        if i in DROP_INDICES:
            continue
        ground_truth = FIXED_29_GROUND_TRUTH if i == 29 else c["ground_truth"]
        kept_candidates.append({
            "topic": "+".join(c["topic_guess"]),
            "question": c["question"],
            "ground_truth": ground_truth,
        })

    merged = kept_hand_written + NEW_HAND_WRITTEN + kept_candidates + OUT_OF_DOMAIN

    OUT_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"合并完成，共 {len(merged)} 条：")
    print(f"  保留的原手写题（sleep~psychiatrist）: {len(kept_hand_written)}")
    print(f"  新增手写题（breakup/exam_anxiety）: {len(NEW_HAND_WRITTEN)}")
    print(f"  审核后保留的自动生成候选题: {len(kept_candidates)}（丢弃 {len(DROP_INDICES)} 条）")
    print(f"  重新设计的真负例: {len(OUT_OF_DOMAIN)}")


if __name__ == "__main__":
    main()
