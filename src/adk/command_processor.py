from pathlib import Path
from typing import Any, cast, Dict, List, Optional

from adk.api.local_api import LocalApi
from adk.api.remote_api import RemoteApi
from adk.decorators import log_function
from adk.exceptions import (AppConfigNotFound, ApplicationNotComplete, ApplicationNotFound, DirectoryAlreadyExists,
                            ExperimentNotRun, NetworkNotAvailableForApplication, ResultDirectoryNotAvailable)
from adk.type_aliases import ApplicationType, ExperimentType, ErrorDictType, ResultType
from adk import utils


class CommandProcessor:
    """
    Class for redirecting the commands to the local or remote api.

    Args:
        remote_api: the api for handling remote commands
        local_api: the api for handling local commands

    """
    def __init__(self, remote_api: RemoteApi, local_api: LocalApi):
        self.__remote = remote_api
        self.__local = local_api

    @log_function
    def login(self, host: str, username: str, password: str) -> None:
        """
        Redirects login to remote api.

        Args:
            host: host to log on to
            username: the user
            password: the password

        """
        self.__remote.login(username=username, password=password, host=host)

    @log_function
    def logout(self, host: Optional[str]) -> bool:
        """
        Redirects logout to remote api.

        Args:
            host: host to log out from
        """
        return self.__remote.logout(host=host)

    def applications_create(self, application_name: str, roles: List[str], application_path: Path) -> None:
        """
        Redirects application create to local api.

        Args:
            application_name: application name
            roles: the roles used for this application
            application_path: location of application files

        """
        self.__local.create_application(application_name, roles, application_path)

    @log_function
    def applications_init(self, application_path: Path) -> None:
        """
        Redirects application int to local api.

        Args:
            application_path: location of application files

        """
        self.__local.init_application(application_path)

    @log_function
    def applications_upload(self, application_name: str, application_path: Path) -> bool:
        """
        Upload the application to the remote server. An app version is created (but disabled) and the related
        objects are created.

        Args:
            application_name: application name
            application_path: location of application files

        Returns:
            True when uploaded successfully, otherwise False
        """
        app_config = self.__local.get_application_config(application_name)
        if app_config:
            application_data = self.__local.get_application_data(application_path)
            app_result = self.__local.get_application_result(application_name)
            if app_result is not None:
                try:
                    application_data = self.__remote.upload_application(application_path=application_path,
                                                                        application_data=application_data,
                                                                        application_config=app_config,
                                                                        application_result=app_result)
                except Exception as e:
                    # Something went wrong
                    # write the application_data we have until now and rethrow exception
                    raise e
                finally:
                    self.__local.set_application_data(application_path, application_data)
            else:
                raise ApplicationNotComplete(application_name)
        else:
            raise ApplicationNotFound(application_name)

        return True

    @log_function
    def applications_publish(self, application_path: Path) -> bool:
        """
        Publish the application to the remote server. With this command we try to enable the current app version.

        Args:
            application_path: location of application files

        Returns:
            True when published successfully, otherwise False
        """
        application_data = self.__local.get_application_data(application_path)
        published = self.__remote.publish_application(application_data=application_data)
        self.__local.set_application_data(application_path, application_data)

        return published

    @log_function
    def applications_list(self, remote: bool, local: bool) -> Dict[str, List[ApplicationType]]:
        """
        List the applications available to the user on remote/local/both

        Args:
            remote: Boolean flag for listing remote applications
            local: Boolean flag for listing local applications

        Returns:
            A dictionary containing 'remote' & 'local' keys with
            value as list of applications available to the user

        """
        app_list = {}
        if remote:
            app_list['remote'] = self.__remote.list_applications()

        if local:
            app_list['local'] = self.__local.list_applications()

        return app_list

    @log_function
    def applications_delete(self, application_name: Optional[str], application_path: Path) -> bool:
        """get the remote application id before we delete the local application"""
        application_id = self.__local.get_application_id(application_path)
        deleted_completely_remote = \
            self.__remote.delete_application(application_id) if application_id is not None else True
        # TODO we don't have to update manifest, it will be deleted now, unless we introduce a --remote flag
        # application_data = self.__local.get_application_data(application_path)
        # if "application_id" in application_data["remote"]:
        #     del application_data["remote"]["application_id"]
        # if "slug" in application_data["remote"]:
        #     del application_data["remote"]["slug"]
        # self.__local.set_application_data(application_path, application_data)
        deleted_completely_local = self.__local.delete_application(application_name, application_path)

        return deleted_completely_local and deleted_completely_remote

    @log_function
    def applications_validate(self, application_name: str, application_path: Path, local: bool = True) -> ErrorDictType:
        """
        Validate the application. Depending on parameter local the validation is done locally or remote.

        Args:
            application_name: application name
            application_path: location of application files
            local: is the application local or not

        Returns:
            Dictionary with errors, warnings found
        """
        if local:
            return self.__local.validate_application(application_name, application_path)
        return self.__remote.validate_application(application_name)

    @log_function
    def __is_application_local(self, application_name: str) -> bool:
        # return config_manager.application_exists(application_name)
        pass

    @log_function
    def experiments_create(self, experiment_name: str, application_name: str, network_name: str, local: bool,
                           path: Path) -> None:
        """
        Create the experiment directory with files at the given path for the application
        using the specified network.

        Args:
            experiment_name: Name of the directory where experiment will be created
            application_name: Name of the application for which to create the experiment
            network_name: Name of the network to use for creating the experiment
            local: Boolean flag specifying whether experiment is local or remote
            path: Location where the experiment (directory) will be created

        Raises:
            DirectoryAlreadyExists: Raised when directory (or file) experiment_name already exists

        """
        experiment_name = experiment_name.lower()
        experiment_path = path / experiment_name

        # check if experiment path is already an existing dir/file
        if experiment_path.exists():
            raise DirectoryAlreadyExists('Experiment', str(experiment_path))

        if local:
            app_config = self.__local.get_application_config(application_name)
        else:
            app_config = self.__remote.get_application_config(application_name)

        if app_config:
            if self.__local.is_network_available(network_name, app_config):
                self.__local.experiments_create(experiment_name=experiment_name,
                                                application_name=application_name,
                                                network_name=network_name,
                                                local=local,
                                                path=path,
                                                app_config=app_config)
            else:
                raise NetworkNotAvailableForApplication(network_name, application_name)

        else:
            raise AppConfigNotFound(application_name)

    @log_function
    def experiments_list(self) -> List[ExperimentType]:
        """ Get the remote experiments for the authenticated user """
        return self.__remote.experiments_list()

    @log_function
    def experiments_validate(self, experiment_path: Path) -> ErrorDictType:
        """ Validate the local experiment files

        Args:
            experiment_path: directory where experiment resides

        Returns:
            Dictionary with errors, warnings found
        """
        return self.__local.validate_experiment(experiment_path)

    @log_function
    def experiments_delete_remote_only(self, experiment_id: str) -> bool:
        """
        Delete the remote experiment.

        Args:
            experiment_id: experiment to delete

        Returns:
            Successful or not

        """
        return self.__remote.delete_experiment(experiment_id)

    @log_function
    def experiments_delete(self, experiment_name: str, experiment_path: Path) -> bool:
        """
        Get the remote experiment id registered for this experiment when it run remote, delete this remote experiment.
        Then delete the local experiment.

        Args:
            experiment_name: experiment name
            experiment_path: location of experiment files

        Returns:
            Successful or not
        """
        deleted_remote = True
        remote = not self.__local.is_experiment_local(experiment_path=experiment_path)
        if remote:
            experiment_id = self.__local.get_experiment_id(experiment_path)
            deleted_remote = self.__remote.delete_experiment(experiment_id) if experiment_id is not None else True
        deleted_completely_local = self.__local.delete_experiment(experiment_name, experiment_path)

        return deleted_completely_local and deleted_remote

    @log_function
    def experiments_run(self, experiment_path: Path, block: bool = True) -> Optional[List[ResultType]]:
        """ Run the experiment and get the results. When running a remote experiment depending on the parameter block
        we wait for the results, otherwise None is returned (results not yet available).
        With qne experiment results a next try can be done to get the results

        Args:
            experiment_path: location of experiment files
            block: do we wait for the result or not

        Returns:
            None if remote results are not yet available, otherwise True
        """
        results: Optional[List[ResultType]]
        local = self.__local.is_experiment_local(experiment_path=experiment_path)
        if local:
            results = self.__local.run_experiment(experiment_path)
        else:
            experiment_data = self.__local.get_experiment_data(experiment_path)
            round_set, experiment_id = self.__remote.run_experiment(experiment_data)
            self.__local.set_experiment_id(experiment_id, experiment_path)
            self.__local.set_experiment_round_set(round_set, experiment_path)
            results = self.__remote.get_results(round_set, block)

        if results is not None:
            self.__store_results(results, experiment_path)
        return results

    @log_function
    def experiments_results(self, all_results: bool, experiment_path: Path) -> Optional[List[ResultType]]:
        """ Get the experiment results

        Returns:
            None if remote results are not (yet) available, otherwise the results
        """
        results = None
        remote = not self.__local.is_experiment_local(experiment_path=experiment_path)
        if remote:
            round_set = self.__local.get_experiment_round_set(experiment_path)
            if round_set is not None:
                if not self.__results_available(round_set, experiment_path):
                    results = self.__remote.get_results(round_set)
                    if results is not None:
                        self.__store_results(results, experiment_path)
                else:
                    results = self.__get_results(experiment_path=experiment_path)
            else:
                raise ExperimentNotRun(str(experiment_path))
        else:
            results = self.__get_results(experiment_path=experiment_path)

        return results

    @log_function
    def __results_available(self, round_set_url: str, experiment_path: Path) -> bool:
        processed_result_json_file = experiment_path / 'results' / 'processed.json'
        if processed_result_json_file.exists():
            results = self.__get_results(experiment_path=experiment_path)
            if results and results[0]["round_set"] == round_set_url:
                return True
        return False

    @log_function
    def __store_results(self, results: List[ResultType], experiment_path: Path) -> None:
        processed_results_directory = experiment_path / "results"
        if not processed_results_directory.exists():
            processed_results_directory.mkdir(parents=True)

        processed_result_json_file = processed_results_directory / 'processed.json'
        utils.write_json_file(processed_result_json_file, results, encoder_cls=utils.ComplexEncoder)

    @log_function
    def __get_results(self, experiment_path: Path) -> List[ResultType]:
        processed_results_directory = experiment_path / "results"
        if not processed_results_directory.exists():
            raise ResultDirectoryNotAvailable(str(processed_results_directory))

        processed_result_json_file = processed_results_directory / 'processed.json'
        return cast(List[ResultType], utils.read_json_file(processed_result_json_file))

    @log_function
    def networks_list(self, remote: bool, local: bool) -> Dict[str, List[Dict[str, Any]]]:
        """
        List the networks available to the user on remote/local/both

        Args:
            remote: Boolean flag for listing remote networks
            local: Boolean flag for listing local networks

        Returns:
            A dictionary containing 'remote' & 'local' keys with
            value as list of networks available to the user

        """
        network_list = {}
        if remote:
            network_list['remote'] = self.__remote.list_networks()

        if local:
            network_list['local'] = self.__local.list_networks()

        return network_list

    @log_function
    def networks_update(self, overwrite: bool) -> bool:
        """
        Get the remote networks and store them in ./networks

        Args:
            overwrite: Boolean flag for overwriting the local networks with the remote networks otherwise merge

        Returns:
            True if all went right

        """
        return self.__remote.update_networks(overwrite=overwrite)
