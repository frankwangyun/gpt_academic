from toolbox import CatchException, update_ui, get_conf
from .crazy_utils import request_gpt_model_in_new_thread_with_ui_alive, input_clipping
import requests
from bs4 import BeautifulSoup
from request_llms.bridge_all import model_info
import urllib.request
from functools import lru_cache

@lru_cache
def get_auth_ip():
    try:
        external_ip = urllib.request.urlopen('https://v4.ident.me/').read().decode('utf8')
        return external_ip
    except:
        return '114.114.114.114'

def searxng_request(query, proxies, categories='general', searxng_url=None):
    if searxng_url is None:
        url = get_conf("SEARXNG_URL")
    else:
        url = searxng_url
    params = {
        'q': query,         # 搜索查询
        'format': 'json',   # 输出格式为JSON
        'language': 'zh',   # 搜索语言
        'categories': categories
    }
    headers = {
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36',
        'X-Forwarded-For': get_auth_ip(),
        'X-Real-IP': get_auth_ip()
    }
    results = []
    response = requests.post(url, params=params, headers=headers, proxies=proxies)
    if response.status_code == 200:
        json_result = response.json()
        for result in json_result['results']:
            item = {
                "title": result["title"],
                "content": result["content"],
                "link": result["url"],
            }
            results.append(item)
        return results
    else:
        if response.status_code == 429:
            raise ValueError("Searxng（在线搜索服务）当前使用人数太多，请稍后。")
        else:
            raise ValueError("在线搜索失败，状态码: " + str(response.status_code) + '\t' + response.content.decode('utf-8'))

def scrape_text(url, proxies) -> str:
    """Scrape text from a webpage

    Args:
        url (str): The URL to scrape text from

    Returns:
        str: The scraped text
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.61 Safari/537.36',
        'Content-Type': 'text/plain',
    }
    try:
        response = requests.get(url, headers=headers, proxies=proxies, timeout=8)
        if response.encoding == "ISO-8859-1": response.encoding = response.apparent_encoding
    except:
        return "无法连接到该网页"
    soup = BeautifulSoup(response.text, "html.parser")
    for script in soup(["script", "style"]):
        script.extract()
    text = soup.get_text()
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    text = "\n".join(chunk for chunk in chunks if chunk)
    return text

@CatchException
def 连接网络回答问题(txt, llm_kwargs, plugin_kwargs, chatbot, history, system_prompt, user_request):

    history = []    # 清空历史，以免输入溢出
    chatbot.append((f"请结合互联网信息回答以下问题：{txt}",
                    "[Local Message] 请注意，您正在调用一个[函数插件]的模板，该模板可以实现ChatGPT联网信息综合。该函数面向希望实现更多有趣功能的开发者，它可以作为创建新功能函数的模板。您若希望分享新的功能模组，请不吝PR！"))
    yield from update_ui(chatbot=chatbot, history=history) # 刷新界面

    # ------------- < 第1步：爬取搜索引擎的结果 > -------------
    from toolbox import get_conf
    proxies = get_conf('proxies')
    categories = plugin_kwargs.get('categories', 'general')
    searxng_url = plugin_kwargs.get('searxng_url', None)
    urls = searxng_request(txt, proxies, categories, searxng_url)
    history = []
    if len(urls) == 0:
        chatbot.append((f"结论：{txt}",
                        "[Local Message] 受到google限制，无法从google获取信息！"))
        yield from update_ui(chatbot=chatbot, history=history) # 刷新界面
        return
    # ------------- < 第2步：依次访问网页 > -------------
    max_search_result = 5   # 最多收纳多少个网页的结果
    for index, url in enumerate(urls[:max_search_result]):
        res = scrape_text(url['link'], proxies)
        history.extend([f"第{index}份搜索结果：", res])
        chatbot.append([f"第{index}份搜索结果：", res[:500]+"......"])
        yield from update_ui(chatbot=chatbot, history=history) # 刷新界面

    # ------------- < 第3步：ChatGPT综合 > -------------
    i_say = f"从以上搜索结果中抽取信息，然后回答问题：{txt}"
    i_say, history = input_clipping(    # 裁剪输入，从最长的条目开始裁剪，防止爆token
        inputs=i_say,
        history=history,
        max_token_limit=min(model_info[llm_kwargs['llm_model']]['max_token']*3//4, 8192)
    )
    gpt_say = yield from request_gpt_model_in_new_thread_with_ui_alive(
        inputs=i_say, inputs_show_user=i_say,
        llm_kwargs=llm_kwargs, chatbot=chatbot, history=history,
        sys_prompt="请从给定的若干条搜索结果中抽取信息，对最相关的两个搜索结果进行总结，然后回答问题。"
    )
    chatbot[-1] = (i_say, gpt_say)
    history.append(i_say);history.append(gpt_say)
    yield from update_ui(chatbot=chatbot, history=history) # 刷新界面 # 界面更新

