# comfyui-xhcyai

XHCY AI（[ai.xhcyai.org](https://ai.xhcyai.org)）的 ComfyUI 节点。

在节点里填写自己的访问密钥，用来调用官方站点。密钥也可以只保存在本机，不要写进工作流。

## 安装

1. 把仓库放到 ComfyUI 的插件目录：

   ```
   ComfyUI/custom_nodes/comfyui-xhcyai/
   ```

2. 安装依赖：

   ```
   pip install -r requirements.txt
   ```

3. 重启 ComfyUI，在节点面板的 **XHCY** 分类里使用。

## 支持的功能

图像、视频、文本各自一个家族一个节点，用下拉里的变体切换。图像节点不接参考图就是文生图，接上参考图就是多图参考。

**图像**

- GPT Image 2、GPT Image 2.5、GPT Image 2.6：文生图 / 多图参考
- Nano Banana：文生图 / 多图参考
- Seedream 5.0：文生图 / 多图参考 / 图层拆分

**视频**

- MiniMax H3：文生视频、首尾帧、多模态参考、768P→2K 再生成、提示词增强
- Seedance 2.0：文生、首尾帧、多模态参考
- 视频超分：按任务号或公网视频地址提升分辨率

**文本**

- 文本 / 对话
- 智能分析：按角色产出提示词、分镜或参数建议

各变体支持的分辨率、时长和比例不同。选到当前变体不支持的组合时，节点会在提交前说明。

## 近期更新

- 大参考视频上传不再被握手阶段的短超时打断。
- 部分网络下调用网关时，未完成的握手会重试，已发出的请求不会再提交一次。
- Nano Banana 图像结果支持内嵌图片，并改为提交后轮询。
- 增加视频超分节点；访问密钥留空时可以使用本机已保存的密钥。
- 文本下拉增加 gpt-6.2-sol。看图能力未确认，接了图片不会提交。
- GPT Image 下拉增加 gpt-image-2.6-flare 与 gpt-image-2.6-sunburst。画幅 auto 提交 size=auto；画质只提交 auto / low / medium / high。
- nano-banana-2 与 gemini-nano-banana-2.1 预留 1:4、4:1、1:8、8:1。站点尚未开放，选中后不会提交。nano-banana-pro 与 gemini-2.5-flash-image 不接受这些比例，也不会换模。
