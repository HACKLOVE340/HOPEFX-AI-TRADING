class FeatureFlag:
    def __init__(self):
        self.flags = {}

    def add_flag(self, flag_name, is_active=False):
        self.flags[flag_name] = is_active

    def set_flag(self, flag_name, is_active):
        if flag_name in self.flags:
            self.flags[flag_name] = is_active
        else:
            raise ValueError(f"Feature flag '{flag_name}' does not exist.")

    def is_flag_active(self, flag_name):
        return self.flags.get(flag_name, False)


class UserCohort:
    def __init__(self):
        self.cohorts = {}

    def add_cohort(self, cohort_name, user_ids):
        self.cohorts[cohort_name] = user_ids

    def is_user_in_cohort(self, user_id, cohort_name):
        return user_id in self.cohorts.get(cohort_name, [])


class FeatureFlagManager:
    def __init__(self):
        self.feature_flags = FeatureFlag()
        self.user_cohorts = UserCohort()

    def add_cohort(self, cohort_name, user_ids):
        self.user_cohorts.add_cohort(cohort_name, user_ids)

    def add_feature_flag(self, flag_name):
        self.feature_flags.add_flag(flag_name)

    def enable_feature_for_cohort(self, flag_name, cohort_name):
        if self.feature_flags.is_flag_active(flag_name) and self.user_cohorts.is_user_in_cohort(cohort_name):
            return True
        return False

    def set_feature_flag(self, flag_name, is_active):
        self.feature_flags.set_flag(flag_name, is_active)

    def is_feature_active(self, flag_name, user_id, cohort_name):
        return self.enable_feature_for_cohort(flag_name, cohort_name) and self.feature_flags.is_flag_active(flag_name)
