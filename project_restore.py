#!/usr/bin/env python
import logging
import os
import docker
from compose.cli.main import TopLevelCommand
from compose.cli.command import get_project

#
# This scripts aims to help project update locally
#
#                        +------------------+     +-----------------+
#                  +-----| select database  +-----+has purge option?|
#                  |     +------------------+     +----+------+-----+
#                  |                                   |      |
#                  |     +------------------+      yes |    no|
#                  |     |                  <----------+      |
#                  |     | purge local files|                 |
#                  |     |                  +----------+      |
#                  |     +--------+---------+          |      |
#                  +-----------------------------------+      |
#                                                 +----v------v-----+
#  +-----------------+   +------------------+ yes | database file   |
#  |restore template | no|                  <-----+ exists locally  |
#  |                 <---+ template exists? |     | in cache?       |
#  +-------+--^------+   |                  <--+  +--------+--------+
#          |  |          +------------------+  |         no|
#          |  |                   |yes         |           |
#          |  |      yes +--------v---------+  |           |
#          |  +----------+                  |  |  +--------v--------+
#          |             | is cache renew?  |  +--+retrieve database|
#          +------------->                  |     +-----------------+
#                        +------------------+
#                                 |no
#                        +--------v---------+
#                        + restore database |
#                        +------------------+

_logger = logging.getLogger(__name__)

################################################################################
# Constants
################################################################################
PROJECT_NAME = os.path.basename(os.getcwd())
CACHE_FOLDER = "~/.cache/camptocamp"
AWS_BUCKET_NAME = "odoo-dumps"
PG_DB = "odoodb"
PG_DB_TEMPLATE = "{}_template".format(PG_DB)
PG_DB_SAMPLE = "{}_sample".format(PG_DB)
LOG_FILE = "project_restore.log"
CONFIG_FILE = "config.yaml"
MIGRATION_LOG_FILE = "database_migration.log"
ERROR_JSON = "database_migration_errors.json"
MODULES_JSON = "database_migration_modules.json"
ODOO_MIGRATED_DB_URL = "https://upgrade.odoo.com/database/eu1/"
ODOO_POSTFIX_URL = "/upgraded/archive"
GPG_IDENTITY = "3E84782B5BC3B642"

################################################################################
# Variables
################################################################################
TEMPLATE_TO_UPDATE = 0  # Force database template update
PARTIAL_TEMPLATE_RESTORE = 0  # an error has occured during template restore
PURGE = 0  # force cache purge
ODOO_MIGRATION_IDS = None  # values from odoo migration url
DB_FOLDER = "$CACHE_FOLDER/databases/$PROJECT_NAME"  # variates with database from odoo
FILESTORE_FOLDER = "$DB_FOLDER/filestore"  # variates with database from odoo
FORCE_BUILD = 0  # force the reconfigure and build of project and docker image
RESTORE_DATABASE = 0  # force database restore from template


################################################################################
# Cleaning functions
################################################################################

def clean(docker_client, compose_client: compose.project):
    os.remove("{}/*.pg".format(DB_FOLDER))
    os.remove("{}/*.sql".format(DB_FOLDER))
    if PARTIAL_TEMPLATE_RESTORE:
        compose_client.
        compose. run --rm odoo dropdb $PG_DB_TEMPLATE


def purge(docker_client):
    _logger.info("Purge configuration, databases and logs...")
    # close all actual connections
    # docker-compose run --rm odoo psql -c "SELECT pg_terminate_backend(pg_stat_activity.pid) FROM pg_stat_activity WHERE pg_stat_activity.datname = '$PG_DB' AND pid <> pg_backend_pid()"
    # docker-compose run --rm odoo psql -c "SELECT pg_terminate_backend(pg_stat_activity.pid) FROM pg_stat_activity WHERE pg_stat_activity.datname = '$PG_DB_TEMPLATE' AND pid <> pg_backend_pid()"
    # docker-compose run --rm odoo dropdb $PG_DB
    # docker-compose run --rm odoo dropdb $PG_DB_TEMPLATE
    # rm -Rf $DB_FOLDER
    # rm -Rf $FILESTORE_FOLDER
    # rm -Rf $LOG_FILE $ERROR_JSON $MODULES_JSON


################################################################################
# SIG exception management
################################################################################

# function clean_and_exit() {
#   clean
#   kill -HUP 0
#   exit 0
# }

# trap clean_and_exit INT
# trap clean_and_exit SIGINT
# trap clean_and_exit EXIT

################################################################################
# Log formatting
################################################################################

# function log() {
#   echo -e "$(date '+%F %T') INFO \e[1m\e[34m$*\e[0m" |& tee -a $LOG_FILE
# }

################################################################################
# Docker hooks
################################################################################

# function docker_pre_build() {
#   readonly repo=$(git rev-parse --show-toplevel)
#   COMMANDS_START="### DO NOT PUSH ###"
#   COMMANDS_APT="RUN echo 'Acquire::http::Proxy \"http://192.168.1.22:8000\";' > /etc/apt/apt.conf.d/00proxy"
#   COMMANDS_MKDIR_ROOT="RUN mkdir -p /root/.pip"
#   COMMANDS_MKDIR_ODOO="RUN mkdir -p /home/odoo/.pip"
#   COMMANDS_PIP="RUN echo '[global]\ntimeout = 30\ntrusted-host = 192.168.1.22\nindex-url = http://192.168.1.22:8247/simple' | tee /home/odoo/.pip/pip.conf /root/.pip/pip.conf"
#   COMMANDS_END="### END DO NOT PUSH ###
#   "
#   # Add dev dependencies
#   echo -e "## custom\npdbpp\ndictdiffer" > ./odoo/dev_requirements.txt
#
#   for file in $(find . -name "Dockerfile")
#   do
#       echo "Found a Dockerfile $file"
#       sed -i "/^### DO NOT PUSH/,/^### END DO NOT PUSH/d" $file
#       if grep -q "apt-get install" "$file"; then
#           sed '/^LABEL\|MAINTAINER/r'<(
#             echo $COMMANDS_START
#             echo $COMMANDS_APT
#             #echo $COMMANDS_MKDIR_ROOT
#             #echo $COMMANDS_MKDIR_ODOO
#             #echo $COMMANDS_PIP
#             echo $COMMANDS_END
#           ) -i $file
#           echo "Done"
#       fi
#   done
# }
# function docker_post_build() {
#   for file in $(find . -name "Dockerfile")
#   do
#       sed -i "/^### DO NOT PUSH/,/^### END DO NOT PUSH/d" $file
#       git add $file
#   done
# }

################################################################################
# Functional methods
################################################################################

# function yaml() {
#   pip install pyaml
#   eval "$2=$(python -c "import yaml;value = yaml.safe_load(open('$1'))['$2'];print(value if value != 'None' else '')")"
# }

# function db_name_user_input() {
#   echo "--------------------------------------------------------------------------------"
#   echo " Select a database to proceed:"
#   echo "--------------------------------------------------------------------------------"
#   names=(exit $(aws --profile odoo-dumps s3 ls s3://odoo-dumps/ | sort | awk '{print $2}' | rev | cut -c2- | rev))
#   names+=( "no_name" )
#   select name in "${names[@]}"; do
#     [[ $name == "exit" ]] || [[ -z $name ]] && exit 0
#     PG_PROD_DBNAME="$name"
#     return 0
#   done
# }

# function db_name_user_local_input() {
#   files=($(ls $DB_FOLDER | sort -r | grep "^$PG_PROD_DBNAME.*\.gpg$"))
#   if [ "${#files[@]}" -eq "1" ]; then
#     PG_DB_FILENAME="${files[0]}"
#     PG_PROD_DBNAME=$(echo "${files[0]}" | sed -e 's/\.sql.gpg//' | sed -e 's/\.pg.gpg//' | sed -E 's/-[0-9]{8}-[0-9]{6}//')
#   elif [ "${#files[@]}" -gt "1" ]; then
#     echo "--------------------------------------------------------------------------------"
#     echo " Select a local database to proceed (or exit to download a new one):"
#     echo "--------------------------------------------------------------------------------"
#     select name in "${files[@]}"; do
#       [[ $name == "exit" ]] || [[ -z $name ]] && exit 0
#       PG_DB_FILENAME="$name"
#     PG_PROD_DBNAME=$(echo "$name" | sed -e 's/\.sql.gpg//' | sed -e 's/\.pg.gpg//' | sed -E 's/-[0-9]{8}-[0-9]{6}//')
#       return 0
#     done
#   fi
# }

# function retrieve_client_database() {
#
#   if [[ -n $ODOO_MIGRATION_IDS ]]; then
#     PG_PROD_DBNAME="upgraded_$PG_PROD_DBNAME"
#     tmpfile=$(mktemp /tmp/odoo_migrated_database.XXXXX.zip)
#     database_to_retrieve=$ODOO_MIGRATED_DB_URL$ODOO_MIGRATION_IDS$ODOO_POSTFIX_URL
#     log "Retrieving database from Odoo : '$database_to_retrieve'"
#     wget -q --show-progress --output-document "$tmpfile" "$database_to_retrieve"
#     log "Unzipping '$tmpfile' to local cache"
#     unzip -q "$tmpfile" -d "$tmpfile.extract" |& tee -a $LOG_FILE
#     mv "$tmpfile.extract/dump.sql" "$DB_FOLDER/$PG_PROD_DBNAME.sql" &> /dev/null
#     rm -Rf $FILESTORE_FOLDER/$PG_DB
#     mv "$tmpfile.extract/filestore" "$FILESTORE_FOLDER/$PG_DB" &> /dev/null
#     sudo chmod -R 777 $FILESTORE_FOLDER
#     sudo chown -R 999:1000 $FILESTORE_FOLDER
#     PG_DB_FILENAME="$PG_PROD_DBNAME.sql.gpg"
#     gpg -e -r $GPG_IDENTITY "$DB_FOLDER/$PG_PROD_DBNAME.sql" |& tee -a $LOG_FILE
#     rm -Rf $tmpfile
#     rm -Rf "$tmpfile.extract"
#
#     TEMPLATE_TO_UPDATE=1
#
#   elif [[ ! -f $DB_FOLDER/$PG_DB_FILENAME ]]; then
#     databases=$(aws --profile=odoo-dumps s3 ls s3://odoo-dumps/$PG_PROD_DBNAME/ | sort -r | awk '{print $4}')
#     databases=(exit $databases)
#     select database in "${databases[@]}"; do
#       [[ $database == "exit" ]] || [[ -z $database ]] && exit 0
#       PG_DB_FILENAME="$database"
#       break
#     done
#     aws_url="s3://odoo-dumps/$PG_PROD_DBNAME/$PG_DB_FILENAME"
#     log "Retrieve database from AWS : $aws_url"
#     aws --profile=odoo-dumps s3 cp $aws_url "$DB_FOLDER" |& tee -a $LOG_FILE
#     TEMPLATE_TO_UPDATE=1
#   fi
#   PG_DB_FILENAME=$(ls $DB_FOLDER | sort -r | grep ^$PG_PROD_DBNAME.*$ | head -n 1)
#   tmp_pg_filename=$(echo "$PG_DB_FILENAME" | sed -e 's/\.gpg//')
#   if [[ $TEMPLATE_TO_UPDATE == 1 ]] && [[ ! -f $DB_FOLDER/$tmp_pg_filename ]]; then
#     log "Deciphering database"
#     gpg "$DB_FOLDER/$PG_DB_FILENAME" |& tee -a $LOG_FILE |& tee -a $LOG_FILE
#   fi
#   PG_DB_FILENAME=$tmp_pg_filename
# }

# function restore_database() {
#
#   if [ -d $FILESTORE_FOLDER/$PG_DB ]; then
#     log "Restoring the filestore..."
#     docker-compose up -d odoo
#     ODOO_CONTAINER_NAME=$(docker-compose ps | grep "odoo_odoo_1" | awk '{print $1}')
#     docker cp -a $FILESTORE_FOLDER $ODOO_CONTAINER_NAME:/data/odoo
#   fi
#
#   if [[ $TEMPLATE_TO_UPDATE == 1 ]] || [[ $(docker exec -it $DB_CONTAINER_NAME psql -U odoo -lqt | grep -c $PG_DB_TEMPLATE) != 1 ]]; then
#     docker-compose run --rm odoo psql -c "SELECT pg_terminate_backend(pg_stat_activity.pid) FROM pg_stat_activity WHERE pg_stat_activity.datname = '$PG_DB_TEMPLATE' AND pid <> pg_backend_pid()"
#     docker-compose run --rm odoo dropdb $PG_DB_TEMPLATE
#     docker-compose run --rm odoo createdb $PG_DB_TEMPLATE
#     PARTIAL_TEMPLATE_RESTORE=1
#     if [[ $PG_DB_FILENAME =~ \.sql$ ]]; then
#       log "Restoring template from sql..."
#       PGPASSWORD=odoo psql -h localhost -p $DB_CONTAINER_PORT -d $PG_DB_TEMPLATE -U odoo -f $DB_FOLDER/$PG_DB_FILENAME |& tee -a $LOG_FILE
#     else
#       log "Restoring template from pg..."
#       PGPASSWORD=odoo pg_restore --no-privileges --no-owner -h localhost -p $DB_CONTAINER_PORT -U odoo -d $PG_DB_TEMPLATE $DB_FOLDER/$PG_DB_FILENAME |& tee -a $LOG_FILE
#     fi
#     PARTIAL_TEMPLATE_RESTORE=0
#   fi
#
#   log "Restoring database from template..."
#   docker-compose run --rm odoo psql -c "SELECT pg_terminate_backend(pg_stat_activity.pid) FROM pg_stat_activity WHERE pg_stat_activity.datname = '$PG_DB' AND pid <> pg_backend_pid()"
#   docker-compose run --rm odoo dropdb $PG_DB
#   docker-compose run --rm odoo createdb -T $PG_DB_TEMPLATE $PG_DB
# }

# function    migrate() {
#  log "Starting database migration... (see $MIGRATION_LOG_FILE for details)"
#  docker-compose run --rm -e MARABUNTA_MODE=migration -e DB_NAME=$PG_DB odoo rundatabasemigration |& tee -a $MIGRATION_LOG_FILE
#
#  echo "Checking errors and modules..." |& tee -a $MIGRATION_LOG_FILE
#  docker-compose run --rm -e DB_NAME=$PG_DB_SAMPLE -e MARABUNTA_MODE=sample odoo odoo --stop-after-init |& tee -a $MIGRATION_LOG_FILE
#  parse_migration_log.py $MIGRATION_LOG_FILE > $ERROR_JSON
#  invoke migrate.check-modules $PG_DB $PG_DB_TEMPLATE $PG_DB_SAMPLE > $MODULES_JSON
#
#  docker-compose down |& tee -a $MIGRATION_LOG_FILE
# }

# function configure_project() {
#   image=$(docker images -q "$PROJECT_NAME"_odoo:latest 2> /dev/null)
#   if [[ -z $image ]] || [[ $FORCE_BUILD == 1 ]]; then
#     log "Configure project..."
#     [[ -f tasks/requirements.txt ]] && pip install -r tasks/requirements.txt
#     [[ -f odoo/dev_requirements.txt ]] && pip install -r odoo/dev_requirements.txt
#     invoke submodule.init |& tee -a $LOG_FILE
#     invoke submodule.update |& tee -a $LOG_FILE
#     docker_pre_build
#     docker-compose build
#     docker_post_build
#   fi
# }

# function restore_db_container() {
#   docker-compose stop db
#   # Get the docker container name of the database
#   DB_CONTAINER_NAME=$(docker-compose ps | grep "db" | awk '{print $1}')
#   if [[ -z $DB_CONTAINER_NAME ]]; then
#     DB_VOLUME_NAME=$(docker inspect --format '{{range .Mounts}}{{.Name}} {{end}}' "$DB_CONTAINER_NAME")
#     [[ -n $DB_VOLUME_NAME ]] && docker volume rm $DB_VOLUME_NAME
#   fi
#   docker-compose up -d db
#   until [[ $(docker inspect -f {{.State.Running}} "$DB_CONTAINER_NAME") == "true" ]]; do
#       sleep 3;
#   done;
#
#   # Get the docker container port of the database
#   DB_CONTAINER_PORT=$(docker-compose ps | grep "$DB_CONTAINER_NAME" | awk '{print $7}' | cut -d'-' -f1 | cut -d':' -f2)
# }

# function prepare_folders() {
#   rm -Rf $LOG_FILE $ERROR_JSON $MODULES_JSON
#   log "Cache folder for this project : $DB_FOLDER" |& tee -a $LOG_FILE
#
#   [[ ! -d $DB_FOLDER ]] && mkdir -p "$DB_FOLDER"
#   [[ ! -d $FILESTORE_FOLDER ]] && mkdir -p "$FILESTORE_FOLDER"  # implies $DB_FOLDER
# }

################################################################################
# Arg parser
################################################################################
# function usage {
#     echo "usage: $0"
#     echo "  -p|--purge                  purge local file cache and databases" \
#                                         "for this project (implies: -f)"
#     echo "  -r|--restore-database       Force database restore from template"
#     echo "  -b|--build            Force the build of the docker image"
#     echo "  -o|--from-odoo-migration    If database comes from odoo," \
#                                         "indicates the ids as follow id/key" \
#                                         "(i.e. 12345/IRHvI20ZLj'uwzFzAYAVWg==)"
#     exit 1
# }
#
#
# while [[ "$#" -gt 0 ]]; do
#   case $1 in
#   -o|--from-odoo-migration)
#     if [[ -n $2 ]] && [[ ${2:0:1} != "-" ]] && [[ $2 =~ "/" ]]; then
#       ODOO_MIGRATION_IDS=$2
#       RESTORE_DATABASE=1
#       shift
#     else
#       echo "Error: Argument for $1 is missing" >&2
#       exit 1
#     fi
#     ;;
#   -r|--restore-database)
#     RESTORE_DATABASE=1
#     ;;
#   -p|--purge)
#     PURGE=1
#     FORCE_BUILD=1
#     RESTORE_DATABASE=1
#     ;;
#   -b|--build)
#     FORCE_BUILD=1
#     ;;
#   -h|--help)
#     usage
#     ;;
#   *)
#     echo "Unknown parameter passed: $1"
#     exit 1
#     ;;
#   esac
#   shift
# done

class Compose:

    _project = None

    def __init__(self, service, command, rm=True):
        options = {
            "--rm": rm,
            "SERVICE": service,
            "COMMAND": command,
        }
        self._project = get_project(os.getcwd(), config_path=os.getcwd(), project_name=PROJECT_NAME)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._project:
            self._project.down()


if __name__ == "__main__":

    docker_client = docker.from_env()
    main_compopse_options = {}

    with Compose() as compose:


        if purge:
            purge(compose)

    # prepare_folders
    # if [[ $RESTORE_DATABASE == 1 ]]; then
    #   db_name_user_local_input
    #   [[ -z $PG_PROD_DBNAME ]] && db_name_user_input
    # fi
    # [[ -n $PG_PROD_DBNAME ]] && log "/!\ database '$PG_PROD_DBNAME' selected" |& tee -a $LOG_FILE
    #
    # configure_project
    #
    # if [[ $RESTORE_DATABASE == 1 ]]; then
    #   if [[ $PURGE != 1 ]]; then
    #     read -p "Do you wish to update your template [yN]? " answer
    #   else
    #     answer='y'
    #   fi
    #   case ${answer:0:1} in
    #       y|Y )
    #           TEMPLATE_TO_UPDATE=1;
    #         ;;
    #   esac
    #   restore_db_container
    #   retrieve_client_database
    #   restore_database
    # fi
    #
    # exit 0
