import gradio as gr
import PyPDF2
import pandas as pd
import re
from io import BytesIO
import tempfile

class TeletherapyExtractor:
    def __init__(self, content: str):
        self.raw_content = content or ""
        self.clean_content = ' '.join(self.raw_content.split())

    def _extract_regex(self, pattern, content_block=None, group=1, find_all=False):
        target = content_block if content_block else self.clean_content
        try:
            if find_all:
                return re.findall(pattern, target)
            match = re.search(pattern, target, re.IGNORECASE | re.DOTALL)
            return match.group(group).strip() if match else None
        except:
            return None

    def _get_block(self, start_marker, end_marker):
        pattern = fr'{re.escape(start_marker)}(.*?){re.escape(end_marker)}'
        return self._extract_regex(pattern, group=1)

    def process(self):
        c = self.clean_content

        # Extrações básicas
        nome = self._extract_regex(r'Nome do Paciente:\s*(.+?)(?=\s*Matricula)')
        matricula = self._extract_regex(r'Matricula:\s*(\d+)')

        unidade_match = re.search(r'Unidade de tratamento:\s*([^,]+),\s*energia:\s*(\S+)', c)
        unidade = unidade_match.group(1).strip() if unidade_match else "N/A"
        energia_unidade = unidade_match.group(2).strip() if unidade_match else "N/A"

        # Campos e energias
        campos_raw = re.findall(r'Campo (\d+)\s+(\d+X)', c)
        energias_campos = [item[1] for item in campos_raw]
        num_campos = len(energias_campos)

        # Blocos de texto
        block_x = self._get_block('Tamanho do Campo Aberto X', 'Tamanho do Campo Aberto Y')
        block_y = self._get_block('Tamanho do Campo Aberto Y', 'Jaw Y1')
        block_jaw_y1 = self._get_block('Jaw Y1', 'Jaw Y2')
        block_jaw_y2 = self._get_block('Jaw Y2', 'Filtro')
        block_filtros = self._get_block('Filtro', 'MU')
        block_mu = self._get_block('MU', 'Dose')

        def get_vals(block, regex):
            return re.findall(regex, block) if block else []

        x_sizes = get_vals(block_x, r'Campo \d+\s*([\d.]+)\s*cm')
        y_sizes = get_vals(block_y, r'Campo \d+\s*([\d.]+)\s*cm')
        jaw_y1 = get_vals(block_jaw_y1, r'Y1:\s*([+-]?\d+\.\d+)')
        jaw_y2 = get_vals(block_jaw_y2, r'Y2:\s*([+-]?\d+\.\d+)')
        filtros = get_vals(block_filtros, r'Campo \d+\s*([-\w]+)')
        um_vals = get_vals(block_mu, r'Campo \d+\s*([\d.]+)\s*MU')
        dose_vals = re.findall(r'Campo \d+\s+([\d.]+)\s*cGy', c)

        block_ssd = self._get_block('SSD', 'Profundidade')
        ssd_vals = get_vals(block_ssd, r'Campo \d+\s*([\d.]+)\s*cm')

        block_prof = self._get_block('Profundidade', 'Profundidade Efetiva')
        prof_vals = get_vals(block_prof, r'Campo \d+\s*([\d.]+)\s*cm')

        block_eff = self._get_block('Profundidade Efetiva', 'Informações do Campo')
        if not block_eff:
            block_eff = self._get_block('Profundidade Efetiva', 'Campo 1')
        prof_eff_vals = get_vals(block_eff, r'Campo \d+\s*([\d.]+)\s*cm')

        # CORREÇÃO: Nova regex para capturar FSX e FSY
        # Busca por "total fluence" ou "fluência total" seguido de fsx e fsy
        fluencia_matches = re.findall(
            r'(?:total fluence|flu[eê]ncia total).*?fsx\s*=\s*(\d+)\s*mm.*?fsy\s*=\s*(\d+)\s*mm',
            c, re.IGNORECASE | re.DOTALL
        )

        # Monta saída textual e tabela
        output_lines = []
        if nome:
            output_lines.append(f"Nome do Paciente: {nome}")
        if matricula:
            output_lines.append(f"Matricula: {matricula}")
        if unidade != "N/A":
            output_lines.append(f"Unidade de tratamento: {unidade} | Energia: {energia_unidade}")

        table_data = []
        for i in range(max(1, num_campos)):
            def safe(lst, idx, default="N/A"):
                return lst[idx] if idx < len(lst) else default

            # Fluência só se não houver filtro
            f_x_val, f_y_val = "-", "-"
            has_filtro = False
            if i < len(filtros) and filtros[i] not in ('-', 'nan', ''):
                has_filtro = True

            if not has_filtro and fluencia_matches:
                # Tenta pegar a fluência correspondente ao campo
                if i < len(fluencia_matches):
                    f_x_val, f_y_val = fluencia_matches[i]
                else:
                    # Se não houver correspondência, usa a última
                    f_x_val, f_y_val = fluencia_matches[-1]

            row = [
                safe(energias_campos, i, ""),
                safe(x_sizes, i),
                safe(y_sizes, i),
                safe(jaw_y1, i),
                safe(jaw_y2, i),
                safe(filtros, i),
                safe(um_vals, i),
                safe(dose_vals, i),
                safe(ssd_vals, i),
                safe(prof_vals, i),
                safe(prof_eff_vals, i),
                f_x_val,
                f_y_val
            ]
            output_lines.append(", ".join([str(x) for x in row]))
            table_data.append(row)

        df = pd.DataFrame(table_data, columns=[
            "Energia", "X", "Y", "Y1", "Y2", "Filtro", "MU", "Dose", "SSD", "Prof", "P.Ef", "FSX", "FSY"
        ])

        result_text = "\n".join(output_lines) if output_lines else "Nenhum dado extraído."
        return result_text, df, nome

def process_pdf(file):
    if file is None:
        return "Nenhum arquivo enviado.", None, None

    # Gradio fornece um objeto temporário com atributo .name
    try:
        with open(file.name, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            full_text = "\n".join([p.extract_text() or "" for p in reader.pages])
    except Exception as e:
        return f"Erro ao ler PDF: {e}", None, None

    extractor = TeletherapyExtractor(full_text)
    text, df, nome = extractor.process()

    # salva txt temporário para download
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
    tmp.write(text.encode("utf-8"))
    tmp.flush()
    tmp.close()

    return text, df, tmp.name

with gr.Blocks() as demo:
    gr.Markdown("# Processador de Teleterapia")
    gr.Markdown("Extração automática de dados de planejamento clínico")

    with gr.Row():
        with gr.Column(scale=1):
            upload = gr.File(label="Selecionar PDF", file_count="single", type="file")
            btn = gr.Button("Processar")
        with gr.Column(scale=2):
            txt_out = gr.Textbox(label="Texto extraído", lines=10)
            df_out = gr.Dataframe(headers=["Energia","X","Y","Y1","Y2","Filtro","MU","Dose","SSD","Prof","P.Ef","FSX","FSY"], interactive=False)
            download = gr.File(label="Baixar TXT")

    btn.click(process_pdf, inputs=[upload], outputs=[txt_out, df_out, download])

if __name__ == "__main__":
    demo.launch()
