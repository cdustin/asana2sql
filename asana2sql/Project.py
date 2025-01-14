from asana2sql import util
import asana.error
import itertools

from asana2sql import fields
from asana2sql import workspace

CREATE_TABLE_TEMPLATE = (
        """CREATE TABLE IF NOT EXISTS "{table_name}" ({columns});""")

#INSERT_OR_REPLACE_TEMPLATE = ("""INSERT OR REPLACE INTO "{table_name}" ({columns}) VALUES ({values});""")
INSERT_OR_REPLACE_TEMPLATE = ("""INSERT INTO "{table_name}" ({columns}) VALUES ({values}) ON CONFLICT (gid) DO UPDATE SET {set_command};""")


SELECT_TEMPLATE = (
        """SELECT {columns} FROM "{table_name}";""")

DELETE_TEMPLATE = (
        """DELETE FROM "{table_name}" WHERE {id_column} = ?;""")

class NoSuchProjectException(Exception):
    def __init__(self, project_id):
        super(NoSuchProjectException, self).__init__(
                "No project with id {}".format(project_id))

class Project(object):
    """Represents a project on Asana.  The class executes commands to bring the
    database into sync with the project data.
    """

    def __init__(self, asana_client, db_client, workspace, config, fields):
        self._asana_client = asana_client
        self._db_client = db_client
        self._workspace = workspace
        self._config = config
        self._direct_fields = []
        self._indirect_fields = []

        self._project_id = self._config.project_id
        self._table_name = self._config.table_name

        self._project_data_cache = None
        self._task_cache = None

        for field in fields:
            self._add_field(field)

    def _project_data(self):
        """Fetch the project data from Asana and cache it."""
        if self._project_data_cache is None:
            try:
                self._project_data_cache = (
                    self._asana_client.projects.find_by_id(self._project_id))
            except asana.error.NotFoundError:
                raise NoSuchProjectException(self._project_id)
        return self._project_data_cache

    def _required_fields(self):
        return set(field_names for field in self._direct_fields + self._indirect_fields
                               for field_names in field.required_fields())

    def _tasks(self):
        if self._task_cache is None:
            self._task_cache = list(self._asana_client.tasks.find_by_project(self._project_id, fields=",".join(self._required_fields())))
            project_tasks = self._asana_client.tasks.find_by_project(self._project_id, fields=",".join(self._required_fields()))
            for task in project_tasks:
                task_id = task['gid']
                sub_tasks = self._asana_client.tasks.subtasks(task_id, fields=",".join(self._required_fields()))
                for sub_task in sub_tasks:
                    print(sub_task['name'])
                    self._task_cache.append(sub_task)
        return self._task_cache


    def table_name(self):
        return util.sql_safe_name(self._table_name if self._table_name else self.project_name())

    def project_name(self):
        return self._project_data()["name"]

    def _add_field(self, field):
        if field.sql_name:
            self._direct_fields.append(field)
        else:
            self._indirect_fields.append(field)

    def create_table(self):
        print("create_table...")
        print(self.table_name())
        sql = CREATE_TABLE_TEMPLATE.format(
                table_name=self.table_name(),
                columns=",".join([
                        field.field_definition_sql() for field in self._direct_fields]))
        print("db write sql:")
        print(sql)
        self._db_client.write(sql)

    def export(self):
        for task in self._tasks():
            self.insert_or_replace(task)

    def insert_or_replace(self, task):
        columns = ",".join(field.sql_name for field in self._direct_fields)
        values = ",".join("?" for field in self._direct_fields)
        #set_command = ",".join(field.sql_name + "=" + ("'" + field.get_data_from_task(task)+ "'") if field.get_data_from_task(task) else next for field in self._direct_fields)
        #set_command = ",".join(field.sql_name + "=" + ("'" + field.get_data_from_task(task)+ "'") if field.get_data_from_task(task) else '' for field in self._direct_fields)
        set_command = ''
        for field in self._direct_fields:
            if set_command != '' and field.get_data_from_task(task):
                set_command = set_command + ', '
            if field.get_data_from_task(task):
                set_command = set_command + " " + field.sql_name + " = " + "'" + field.get_data_from_task(task) + "'" 
        params = [field.get_data_from_task(task) for field in self._direct_fields]
        self._db_client.write(
                INSERT_OR_REPLACE_TEMPLATE.format(
                    table_name=self.table_name(),
                    columns=columns,
                    values=values,
                    set_command=set_command),
                *params)

        for field in self._indirect_fields:
            field.get_data_from_task(task)

    def delete(self, task_id):
        id_field = self._id_field()
        self._db_client.write(
                DELETE_TEMPLATE.format(
                    table_name=self.table_name(),
                    id_column=id_field.sql_name),
                task_id)

    def synchronize(self):
        db_task_ids = self.db_task_ids()
        asana_task_ids = self.asana_task_ids()

        ids_to_remove = db_task_ids.difference(asana_task_ids)

        for task in self._tasks():
            self.insert_or_replace(task)

        for id_to_remove in ids_to_remove:
            self.delete(id_to_remove)

    def asana_task_ids(self):
        return set(task.get("gid") for task in self._tasks())

    def _id_field(self):
        return self._direct_fields[0]  # TODO: make the id field special.

    def db_task_ids(self):
        id_field = self._id_field()
        return set(row[0] for row in self._db_client.read(
                SELECT_TEMPLATE.format(
                    table_name=self.table_name(),
                    columns=id_field.sql_name)))

