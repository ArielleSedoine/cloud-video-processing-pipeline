# Utiliser une image officielle de Python comme base
FROM python:3.12

# Installer les dépendances nécessaires (y compris git, make, et autres outils pour compiler)
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    libtool \
    autoconf \
    pkg-config \
    yasm \
    cmake \
    ffmpeg && \
    apt-get clean

# Cloner le dépôt GPAC depuis GitHub et installer MP4Box
RUN git clone https://github.com/gpac/gpac.git && \
    cd gpac && \
    git checkout v2.4.0 && \ 
    make && make install && \
    rm -f /usr/local/bin/MP4Box && \
    ln -s /gpac/bin/gcc/MP4Box /usr/local/bin/MP4Box  

# Vérifier l'installation correcte de MP4Box
RUN which MP4Box
RUN MP4Box -version

# Définir le fuseau horaire à Toronto (EST)
RUN ln -sf /usr/share/zoneinfo/America/Toronto /etc/localtime && echo "America/Toronto" > /etc/timezone

# Définir le répertoire de travail
WORKDIR /app

# Copier les fichiers de l'application dans le conteneur
COPY main.py requirements.txt /app/

# Installer les dépendances Python
RUN pip install --no-cache-dir -r requirements.txt

# Installer Gunicorn
RUN pip install gunicorn

# Définir le point d'entrée de l'application
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8080", "--timeout", "3600", "main:transcoder_handler"]
