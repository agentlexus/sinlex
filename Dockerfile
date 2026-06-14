FROM anaconda/miniconda:latest

RUN apt-get update && apt-get install -y \
    poppler-utils \
    libpoppler-dev \
    tesseract-ocr \
    tesseract-ocr-rus \
    && rm -rf /var/lib/apt/lists/*

RUN conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main && \
    conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r && \
    conda create -n sinlex python=3.10 -y && \
    conda run -n sinlex conda install -c conda-forge pythonocc-core=7.8.1.1 -y && \
    conda run -n sinlex pip install fastapi uvicorn trimesh cascadio python-multipart numpy pdf2image opencv-python pytesseract requests streamlit openai

COPY visual_server.py /opt/sinlex/visual_server.py
COPY api /opt/sinlex/api
COPY risk_scanner.py /opt/sinlex/risk_scanner.py
COPY expert_analyzer.py /opt/sinlex/expert_analyzer.py
COPY step_analyzer.py /opt/sinlex/step_analyzer.py
COPY project_store.py /opt/sinlex/project_store.py
COPY auth_store.py /opt/sinlex/auth_store.py
COPY payment.py /opt/sinlex/payment.py
COPY extraction_tool /opt/sinlex/extraction_tool

WORKDIR /opt/sinlex
CMD ["conda", "run", "-n", "sinlex", "uvicorn", "visual_server:app", "--host", "0.0.0.0", "--port", "8001"]
