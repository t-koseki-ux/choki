import streamlit as st
import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageChops
import io
import base64
from streamlit_image_coordinates import streamlit_image_coordinates
import streamlit.components.v1 as components

# --- 余白自動トリミング関数（強化版） ---
def trim_vertical_white_space(img, threshold=245):
    """画像の上下の白（またはほぼ白）領域を自動的にトリミングする"""
    rgb_img = img.convert("RGB")
    gray = rgb_img.convert("L")
    # threshold以上の明るさ（ほぼ白）を黒(0)、それ以外（コンテンツ）を白(255)にして境界を明確にする
    bw = gray.point(lambda x: 0 if x >= threshold else 255)
    bbox = bw.getbbox()
    if bbox:
        # bboxは (left, upper, right, lower)
        # 左右は維持し、上下の余白のみをギリギリまでカット
        return img.crop((0, bbox[1], img.width, bbox[3]))
    return img

if "file_name" not in st.session_state:
    st.session_state.file_name = None

def reset_session():
    st.session_state.lines_by_page = {}
    st.session_state.current_page = 0
    st.session_state.img_key = 0
    st.session_state.last_coord = None
    st.session_state.generated_html = None
    st.session_state.concat_states = {}
    st.session_state.role_states = {}

st.set_page_config(layout="wide")
st.title("[PDF自動切り出し＆HTML生成アプリ.13]")

uploaded_file = st.file_uploader("PDFファイルをアップロードしてください", type=["pdf"])

if uploaded_file is not None:
    if st.session_state.file_name != uploaded_file.name:
        reset_session()
        st.session_state.file_name = uploaded_file.name
        st.rerun()

    pdf_bytes = uploaded_file.read()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages = doc.page_count

    # --- 操作パネル ---
    with st.sidebar:
        st.header("🛠️ 操作パネル")
        st.subheader("ページ移動")
        col_prev, col_next = st.columns(2)
        with col_prev:
            if st.button("◀ 前ページ") and st.session_state.current_page > 0:
                st.session_state.current_page -= 1
                st.rerun()
        with col_next:
            if st.button("次ページ ▶") and st.session_state.current_page < total_pages - 1:
                st.session_state.current_page += 1
                st.rerun()
        st.markdown(f"**現在の位置:** {st.session_state.current_page + 1} / {total_pages} ページ")
        st.markdown("---")

        st.subheader("マウスの動作設定")
        action_mode = st.radio("クリック時の動作", ["✒️ 線を引く", "🗑️ 線を消す（線を直接クリック）"])
        
        st.markdown("---")
        st.subheader("線の種類と太さ")
        line_type = st.radio("引く線の種類", ["通常線（境界）", "太赤線（この範囲を除外）"])
        thick_size = 0
        if line_type == "太赤線（この範囲を除外）":
            thick_size = st.slider("太赤線の太さ（px）", 10, 200, 40)
        
        st.markdown("---")
        if st.button("現在のページの線をすべてリセット", type="primary"):
            st.session_state.lines_by_page[st.session_state.current_page] = []
            st.session_state.img_key += 1
            st.session_state.generated_html = None
            st.rerun()

        st.markdown("---")
        st.subheader("出力テンプレート設定")
        template_type = st.radio("テンプレートの種類", ["読み物 (通常)", "択一問題 (単一選択)", "スライド式 (ストーリー)"])
        atom_id = st.text_input("atomid (JSON用)", value="GMT2P3Z1C154")
        
        # 🌟 追加：画像を結合する際の空白サイズ設定
        concat_margin = st.slider("画像結合時の間の空白サイズ（px）", 0, 100, 20)
        
        correct_answer = ""
        if template_type == "択一問題 (単一選択)":
            correct_answer = st.text_input("正答 (例: 101)", value="101")

    # --- メインエリア：画像の表示と線引き ---
    if st.session_state.current_page not in st.session_state.lines_by_page:
        st.session_state.lines_by_page[st.session_state.current_page] = []
    current_lines = st.session_state.lines_by_page[st.session_state.current_page]

    page = doc.load_page(st.session_state.current_page)
    pix = page.get_pixmap(dpi=150)
    img_original = Image.open(io.BytesIO(pix.tobytes("png")))
    img_display = img_original.convert("RGBA")
    
    overlay = Image.new("RGBA", img_display.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    
    for line in current_lines:
        y = line["y"]
        if line["type"] == "通常線（境界）":
            draw.line([(0, y), (img_display.width, y)], fill=(255, 0, 0, 255), width=3)
        else:
            t = line["thickness"]
            draw.rectangle([(0, y - t//2), (img_display.width, y + t//2)], fill=(255, 0, 0, 100))

    img_display = Image.alpha_composite(img_display, overlay).convert("RGB")

    st.markdown(f"### 📄 プレビュー (ページ {st.session_state.current_page + 1})")
    value = streamlit_image_coordinates(
        img_display, 
        key=f"pdf_img_p{st.session_state.current_page}_k{st.session_state.img_key}"
    )
    
    if value is not None:
        coord_str = f"{value['x']}_{value['y']}_{st.session_state.img_key}"
        if st.session_state.last_coord != coord_str:
            st.session_state.last_coord = coord_str
            clicked_y = value["y"]
            
            if "線を引く" in action_mode:
                if not any(l["y"] == clicked_y for l in current_lines):
                    current_lines.append({"y": clicked_y, "type": line_type, "thickness": thick_size})
            elif "線を消す" in action_mode:
                closest_i = -1
                min_dist = 20
                for i, l in enumerate(current_lines):
                    dist = abs(l["y"] - clicked_y)
                    if dist < min_dist:
                        min_dist = dist
                        closest_i = i
                if closest_i != -1:
                    current_lines.pop(closest_i)

            st.session_state.lines_by_page[st.session_state.current_page] = sorted(current_lines, key=lambda x: x["y"])
            st.session_state.generated_html = None
            st.rerun()

    st.markdown("---")

    # --- 切り出しエリア事前計算 ---
    all_areas = []
    for p_num in sorted(st.session_state.lines_by_page.keys()):
        p_lines = st.session_state.lines_by_page[p_num]
        if len(p_lines) < 2:
            continue
            
        p = doc.load_page(p_num)
        p_pix = p.get_pixmap(dpi=150)
        p_orig = Image.open(io.BytesIO(p_pix.tobytes("png")))
        
        for i in range(len(p_lines) - 1):
            line_a = p_lines[i]
            line_b = p_lines[i+1]
            y_start = line_a["y"] + (line_a["thickness"] // 2 if line_a["type"] != "通常線（境界）" else 0)
            y_end = line_b["y"] - (line_b["thickness"] // 2 if line_b["type"] != "通常線（境界）" else 0)
            
            if y_start < y_end:
                crop_img = p_orig.crop((0, y_start, p_orig.width, y_end))
                # 🌟 余白をさらにギリギリまでカット
                crop_img = trim_vertical_white_space(crop_img)
                
                all_areas.append({
                    "id": f"img_{p_num}_{int(y_start)}",
                    "p_num": p_num,
                    "y_start": y_start,
                    "img": crop_img
                })

    # --- UIの出し分け ---
    if all_areas:
        st.subheader("🧩 切り出しエリアの設定")
        
        if template_type == "読み物 (通常)":
            st.write("同じ外枠に囲まれている画像同士が縦に連結されます。")
            visual_groups = []
            current_g = [all_areas[0]]
            current_idxs = [0]
            
            for idx in range(len(all_areas) - 1):
                area = all_areas[idx]
                state_key = f"link_{area['id']}"
                if st.session_state.concat_states.get(state_key, False):
                    current_g.append(all_areas[idx+1])
                    current_idxs.append(idx+1)
                else:
                    visual_groups.append({"areas": current_g, "idxs": current_idxs})
                    current_g = [all_areas[idx+1]]
                    current_idxs = [idx+1]
            visual_groups.append({"areas": current_g, "idxs": current_idxs})
            
            for g_idx, group in enumerate(visual_groups):
                areas = group["areas"]
                idxs = group["idxs"]
                with st.container(border=True):
                    for m_idx, area in enumerate(areas):
                        st.caption(f"画像 {idxs[m_idx]+1}")
                        st.image(area['img'], width=350)
                        if m_idx < len(areas) - 1:
                            if st.button("🔓 連結解除", key=f"btn_unlink_{idxs[m_idx]}"):
                                st.session_state.concat_states[f"link_{area['id']}"] = False
                                st.rerun()
                if g_idx < len(visual_groups) - 1:
                    last_area = areas[-1]
                    if st.button(f"⬇️ 連結する ⬇️", key=f"btn_link_{idxs[-1]}"):
                        st.session_state.concat_states[f"link_{last_area['id']}"] = True
                        st.rerun()

        else:
            if template_type == "択一問題 (単一選択)":
                roles_options = ["除外する", "設問", "選択肢 (101)", "選択肢 (102)", "選択肢 (103)", "選択肢 (104)", "解答", "解説"]
            elif template_type == "スライド式 (ストーリー)":
                roles_options = ["除外する", "全体の問題文"]
                for i in range(1, 11):
                    roles_options.extend([f"スライド{i}: 設問", f"スライド{i}: 解答", f"スライド{i}: 解説"])
            
            for idx, area in enumerate(all_areas):
                with st.container(border=True):
                    col1, col2 = st.columns([1, 2])
                    with col1:
                        st.image(area['img'], width=250)
                    with col2:
                        state_key = f"role_{area['id']}"
                        if state_key not in st.session_state.role_states:
                            st.session_state.role_states[state_key] = roles_options[0]
                        
                        selected_role = st.selectbox(
                            f"画像 {idx+1} の役割", 
                            roles_options, 
                            index=roles_options.index(st.session_state.role_states[state_key]) if st.session_state.role_states[state_key] in roles_options else 0,
                            key=f"sb_{state_key}"
                        )
                        st.session_state.role_states[state_key] = selected_role

    st.markdown("---")
    
    # --- データ生成とHTML出力 ---
    st.subheader("🚀 HTML生成とプレビュー")
    if st.button("💻 HTMLを生成・更新する", type="primary"):
        if not all_areas:
            st.error("有効な切り出しエリアがありません。")
        else:
            preview_fallback_script = """
<style>
#lstPicStory { list-style: none; padding: 0; margin: 0; }
#lstPicStory > li { display: none; }
#lstPicStory > li.lst-current { display: block; }
.box-btn-show-picture { display: flex; align-items: center; justify-content: center; gap: 15px; margin: 20px 0; font-size: 1.2rem; font-weight: bold; }
.btn-show-picture-prev, .btn-show-picture-next { cursor: pointer; padding: 8px 16px; border: 1px solid #ccc; background: #fff; border-radius: 4px; }
.box-collapse-header { cursor: pointer; background: #f5f5f5; padding: 10px; border-bottom: 1px solid #ddd; margin-top: 10px; }
.no-disp { display: none !important; }
</style>
<script>
document.addEventListener('DOMContentLoaded', function() {
    const lis = document.querySelectorAll('#lstPicStory > li');
    const len = lis.length;
    let currentIdx = 0;
    function updateSlide() {
        lis.forEach((li, idx) => {
            if (idx === currentIdx) {
                li.classList.add('lst-current');
                li.style.display = 'block';
            } else {
                li.classList.remove('lst-current');
                li.style.display = 'none';
            }
        });
        document.querySelectorAll('.txt-picture-current').forEach(el => el.textContent = currentIdx + 1);
        document.querySelectorAll('.txt-picture-length').forEach(el => el.textContent = len);
    }
    if (len > 0) {
        document.querySelectorAll('.btn-show-picture-prev').forEach(btn => {
            btn.addEventListener('click', () => { if (currentIdx > 0) { currentIdx--; updateSlide(); } });
        });
        document.querySelectorAll('.btn-show-picture-next').forEach(btn => {
            btn.addEventListener('click', () => { if (currentIdx < len - 1) { currentIdx++; updateSlide(); } });
        });
        updateSlide();
    }

    document.querySelectorAll('.box-collapse-header').forEach(header => {
        header.addEventListener('click', function() {
            const content = this.nextElementSibling;
            if(content && content.classList.contains('box-collapsible')) {
                content.classList.toggle('no-disp');
            }
        });
    });
    
    const btnAnswer = document.getElementById('btnAnswer');
    if (btnAnswer) {
        btnAnswer.addEventListener('click', function() {
            const boxAnswer = document.getElementById('boxAnswer');
            if (boxAnswer) boxAnswer.classList.remove('no-disp');
        });
    }
});
</script>
</body></html>"""

            def img_to_html_tags(img):
                width, height = img.size
                aspect_ratio = f"{width}/{height}"
                
                buffered_png = io.BytesIO()
                img.save(buffered_png, format="PNG")
                png_uri = f"data:image/png;base64,{base64.b64encode(buffered_png.getvalue()).decode()}"
                
                buffered_webp = io.BytesIO()
                img.save(buffered_webp, format="WEBP")
                webp_uri = f"data:image/webp;base64,{base64.b64encode(buffered_webp.getvalue()).decode()}"
                
                return f'<picture><source srcset="{webp_uri}" type="image/webp"><img src="{png_uri}" style="aspect-ratio: {aspect_ratio};"></picture>'

            # 🌟 修正：間に挟む余白サイズを適用するよう変更
            def concat_images_vertically(img_list):
                if not img_list:
                    return None
                if len(img_list) == 1:
                    return img_list[0]
                
                max_w = max(img.width for img in img_list)
                # 画像の高さの合計 + 画像間にはさむ余白の合計
                sum_h = sum(img.height for img in img_list) + concat_margin * (len(img_list) - 1)
                
                dst = Image.new('RGB', (max_w, sum_h), (255, 255, 255))
                cy = 0
                for img in img_list:
                    dst.paste(img, (0, cy))
                    # 次の画像を貼り付けるY座標を計算（画像高さ＋余白サイズ）
                    cy += img.height + concat_margin
                return dst

            if template_type == "読み物 (通常)":
                img_tags_out = ""
                for group in visual_groups:
                    imgs = [a["img"] for a in group["areas"]]
                    final_img = concat_images_vertically(imgs) if len(imgs) > 1 else imgs[0]
                    img_tags_out += f'<section class="box-shadow-1dp"><p>{img_to_html_tags(final_img)}</p></section>\n'

                st.session_state.generated_html = f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0,minimum-scale=1.0"><meta http-equiv="X-UA-Compatible" content="IE=edge"><title>Ｚ会学習アプリ</title>
<link rel="stylesheet" href="../../css/reset.min.css"><link rel="stylesheet" href="../../css/base.min.css"><link rel="stylesheet" href="../../css/custom_main.min.css" />
<script type="application/json" id="contentsMetadata">
{{"atomid": "{atom_id}", "style": "read-only", "answer": "", "version": "1"}}
</script></head><body><main class="box-margin">
{img_tags_out}</main>
<script src="../../contentsInterface/ContentsInterface.js"></script><script src="../../js/lib/jquery.min.js"></script><script src="../../js/lib/jquery-ui.min.js"></script><script src="../../js/lib/jquery.ui.touch-punch.min.js"></script><script src="../../js/custom.min.js"></script><script src="../../js/answer_main.min.js"></script><script src="../../js/zkai_webfont.js"></script></body></html>"""

            elif template_type == "択一問題 (単一選択)":
                role_images_lists = {}
                for area in all_areas:
                    role = st.session_state.role_states.get(f"role_{area['id']}", "除外する")
                    if role not in role_images_lists:
                        role_images_lists[role] = []
                    role_images_lists[role].append(area['img'])
                
                role_images = {r: concat_images_vertically(imgs) for r, imgs in role_images_lists.items()}
                
                q_tag = img_to_html_tags(role_images["設問"]) if "設問" in role_images else ""
                ans_tag = img_to_html_tags(role_images["解答"]) if "解答" in role_images else ""
                exp_tag = img_to_html_tags(role_images["解説"]) if "解説" in role_images else ""
                
                choices_html = ""
                for val in ["101", "102", "103", "104"]:
                    if f"選択肢 ({val})" in role_images:
                        c_tag = img_to_html_tags(role_images[f"選択肢 ({val})"])
                        choices_html += f'<li><input type="radio" name="radio-01" value="{val}"><label>{c_tag}</label></li>\n'

                base_html = f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0,minimum-scale=1.0"><meta http-equiv="X-UA-Compatible" content="IE=edge"><title>Ｚ会学習アプリ</title>
<link rel="stylesheet" href="../../css/reset.min.css"><link rel="stylesheet" href="../../css/base.min.css"><link rel="stylesheet" href="../../css/custom_main.min.css" />
<script type="application/json" id="contentsMetadata">
{{"atomid": "{atom_id}", "style": "single-choice", "answer": ["{correct_answer}"], "version": "1"}}
</script></head><body><main class="box-margin">
<section class="box-shadow-1dp" id="boxSubQuestion"><div class="box-collapse-header"><h2>設問</h2></div><div class="box-collapsible">
<p>{q_tag}</p><ul class="sel-item-border lst-img-radio">{choices_html}</ul></div></section>
<section class="box-btn-answer" id="boxBtnAnswer"><button type="button" class="btn-set-next btn-std box-shadow-2dp" id="btnAnswer">解答する</button></section>
<section class="box-shadow-1dp no-disp" id="boxAnswer"><div class="box-collapse-header"><h2>解答</h2></div><div class="box-collapsible">
<p>{ans_tag}</p><h2>解説</h2><p>{exp_tag}</p></div></section>
</main>
<script src="../../contentsInterface/ContentsInterface.js"></script><script src="../../js/lib/jquery.min.js"></script><script src="../../js/lib/jquery-ui.min.js"></script><script src="../../js/lib/jquery.ui.touch-punch.min.js"></script><script src="../../js/custom.min.js"></script><script src="../../js/answer_main.min.js"></script><script src="../../js/zkai_webfont.js"></script></body></html>"""
                st.session_state.generated_html = base_html.replace('</body></html>', preview_fallback_script)

            elif template_type == "スライド式 (ストーリー)":
                role_images_lists = {}
                for area in all_areas:
                    role = st.session_state.role_states.get(f"role_{area['id']}", "除外する")
                    if role not in role_images_lists:
                        role_images_lists[role] = []
                    role_images_lists[role].append(area['img'])
                
                role_images = {r: concat_images_vertically(imgs) for r, imgs in role_images_lists.items()}

                q_global = role_images.get("全体の問題文")
                global_html = ""
                if q_global:
                    global_html = f'''      <section class="box-shadow-1dp">
            <div class="box-collapse-header box-expand">
                <h2>問題文</h2>
            </div>
            <div class="box-collapsible">
                <p>{img_to_html_tags(q_global)}</p>
            </div>
        </section>\n'''

                slides_html = ""
                max_slide = 0
                for role in role_images.keys():
                    if role.startswith("スライド"):
                        try:
                            s_num = int(role.split("スライド")[1].split(":")[0])
                            max_slide = max(max_slide, s_num)
                        except:
                            pass

                for i in range(1, max_slide + 1):
                    s_q = role_images.get(f"スライド{i}: 設問")
                    s_a = role_images.get(f"スライド{i}: 解答")
                    s_e = role_images.get(f"スライド{i}: 解説")

                    if not s_q and not s_a and not s_e:
                        continue

                    li_class = ' class="lst-current"' if i == 1 else ''
                    slides_html += f'           <li{li_class}>\n'

                    if s_q:
                        slides_html += f'''             <section class="box-shadow-1dp">
                    <div class="box-collapse-header">
                        <h2>設問</h2>
                    </div>
                    <div class="box-collapsible">
                        <p>{img_to_html_tags(s_q)}</p>
                    </div>
                </section>\n'''
                    if s_a or s_e:
                        slides_html += f'''             <section class="box-shadow-1dp">
                    <div class="box-collapse-header">
                        <h2>解答</h2>
                    </div>
                    <div class="box-collapsible">\n'''
                        if s_a:
                            slides_html += f'                       <p>{img_to_html_tags(s_a)}</p>\n'
                        if s_e:
                            slides_html += f'                       <h2>解説</h2>\n                     <p>{img_to_html_tags(s_e)}</p>\n'
                        slides_html += '                    </div>\n                </section>\n'
                    slides_html += '            </li>\n'

                btn_controls = '''      <section class="box-btn-show-picture">
            <button type="button" class="box-shadow-2dp btn-show-picture-prev">◀ 前へ</button>
            <span class="txt-picture-current"></span>
            /
            <span class="txt-picture-length"></span>
            <button type="button" class="box-shadow-2dp btn-show-picture-next">次へ ▶</button>
        </section>\n'''

                base_html = f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0,minimum-scale=1.0"><meta http-equiv="X-UA-Compatible" content="IE=edge"><title>Ｚ会学習アプリ</title>
<link rel="stylesheet" href="../../css/reset.min.css"><link rel="stylesheet" href="../../css/base.min.css"><link rel="stylesheet" href="../../css/custom_main.min.css" />
<script type="application/json" id="contentsMetadata">
{{"atomid": "{atom_id}", "style": "read-only", "answer": "", "version": "1"}}
</script></head><body>  <main class="box-margin">
{global_html}{btn_controls}     <ul class="lst-pic-story" id="lstPicStory">
{slides_html}       </ul>
{btn_controls}  </main>
<script src="../../contentsInterface/ContentsInterface.js"></script><script src="../../js/lib/jquery.min.js"></script><script src="../../js/lib/jquery-ui.min.js"></script><script src="../../js/lib/jquery.ui.touch-punch.min.js"></script><script src="../../js/custom.min.js"></script><script src="../../js/answer_main.min.js"></script><script src="../../js/zkai_webfont.js"></script></body></html>"""
                
                st.session_state.generated_html = base_html.replace('</body></html>', preview_fallback_script)

            # 🌟 修正：「設定がリセットされる」不具合の原因だった st.rerun() を削除しました

    if st.session_state.generated_html is not None:
        st.markdown("---")
        components.html(st.session_state.generated_html, height=800, scrolling=True)
        st.download_button(
            label="📄 この内容でHTMLファイルを最終保存",
            data=st.session_state.generated_html,
            file_name="output.html",
            mime="text/html"
        )