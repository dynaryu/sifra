import abc
import importlib
import collections
import inspect



class NoDefaultException(Exception):
    """
    Thrown when a :py:class:`_Base` is created without providing values for one
    or more :py:class:`Element`s which do not have default values.

    Note that users should never be instantiating or subclassing
    :py:class:`_Base` directly. One should extend a class returned by
    :py:func:`generate_element_base`, which returns a class which extends
    :py:class:`_Base`.
    """
    pass



class ValidationError(Exception):
    """
    Thrown when validation of some item fails. Some examples of when this may
    occur are:

        - A value for an :py:class:`Element` is provided which is not an
          an instance of the type specified for the Element (which is specified
          via argument *cls* to :py:meth:`Element.__init__`).

        - One of the validators provided for an element (see the agument
          *validators* to :py:class:`Element.__init__`) fails or raises an
          exception of this type.
    """
    pass



class AlreadySavedException(Exception):
    """
    Raised if an attempt is made to save a 'Document' which has previously been
    saved.
    """
    pass



class DisallowedElementException(ValueError):
    """
    Raised if an an attempt is made to define an element with a dissallowed
    name. Dissallowed names are specified by
    :py:attr:StructuralMeta.DISALLOWED_FIELDS.
    """
    pass



class MultipleBasesOfTypeBaseError(ValueError):
    """
    Raised if an attempt is made to define a class which inherits from
    multiple classes (``c``) for which ``issubclass(type(c), StructuralMeta)``
    is *True*.

    The reason to dissalow multiple inheritance of said classes is to conform
    to the structure of XML, where an element can only have one parent. This may
    not turn out to be an issue as other interpretations of class hierachies in
    the context of XML may be sensible/feasible... but the semantics and
    practicalities would need to be considered so stop this for now and see how
    we go.
    """
    pass



def jsonify(obj, flatten):
    """
    Convert an object to a representation that can be converted to a JSON document.

    The algorithm is:

        - if the object has a method ``__jsonify__``, return the result of calling it, otherwise
        - if ``isinstance(obj, dict)``, transform the key/value (``k:v``) pairs with
            ``jsonify(k): jsonify(v)``, otherwise
        - if the object is iterable but not a string, transform the elements (``v``)
            with ``jsonify(v)``.
    """

    if hasattr(obj, '__jsonify__'):
        # should probably check the number of args
        return obj.__jsonify__(flatten)
    if isinstance(obj, dict):
        return {jsonify(k, flatten) : jsonify(v, flatten) for k, v in obj.iteritems()}
    if isinstance(obj, collections.Iterable) and not isinstance(obj, basestring):
        return [jsonify(v, flatten) for v in obj]
    return obj



class Pythonizer(object):
    """
    Functor for converting JSONable objects to Python classes.

    Plea

    :param module_name: The name of a Python module.
    """

    def __init__(self, module_name):
        self.module_name = module_name

    @staticmethod
    def _class_getter(mod_class):
        return getattr(importlib.import_module(mod_class[0]), mod_class[1])

    def __call__(self, obj):
        """
        Convert a 'jsonified' object to a Python object. This is the inverse of
        :py:func:`jsonify`.

        A python instance ``c`` should be eqivalent to ``__call__(jsonify(c))``
        with respect to the data returned by ``__jsonify__`` if the object has that
        method or the object as a whole otherwise.
        """

        if isinstance(obj, dict):
            if 'class' in obj:
                cls = obj.pop('class')
                return self._class_getter(cls)(**self.__call__(obj))
            return {str(k): self.__call__(v) for k, v in obj.iteritems()}
        if isinstance(obj, list):
            return [self.__call__(v) for v in obj]
        return obj



class Element(object):
    """
    Represents an element of a model. If a model were represented in a relational
    database, this is analgous to a field in a table.
    """

    @staticmethod
    def NO_DEFAULT():
        """
        A callable that can be used to signal that an Element has no default
        value. Simply raises a :py:exception:`NoDefaultException`.
        """

        raise NoDefaultException()

    def __init__(self, cls, description, default=None, validators=None):
        self.cls = cls
        self.description = description
        self._default = default
        self.validators = validators

    @property
    def default(self):
        if self._default is False:
            raise NoDefaultException()
        return self._default() if callable(self._default) else self._default

    def __jsonify__(self, val, flatten):
        """
        Convert *val* to a form that can be JSON sersialised.
        """

        self.__validate__(val)
        return jsonify(val, flatten)

    def __validate__(self, val):
        """
        Validate *val*. This checks that *val* is of subclass ``eval(self.cls)``
        and that no :py:attr:`validators` either return *False* or raise
        exceptions.

        :py:raises:`ValidationError`.
        """

        # Ideally, we'd like to do the following manipulation of self.cls in
        # the constructor. However, at the time the constructor is called, we
        # don't have self.to_python, which is set on this instance in the
        # metaclass StructuralMeta at the time the elements are handled. We
        # could get around this by defining the element class for a module in
        # a way similar to that employed in generate_element_base.
        if isinstance(self.cls, basestring):
            self.cls = [self.to_python.module_name, self.cls]
        try:
            cls = self.to_python._class_getter(self.cls)
        except:
            # hope that we have a builtin
            cls = eval(self.cls[1])
            self.cls = ['__builtin__', self.cls[1]]

        if not isinstance(val, cls):
            raise ValidationError('value is not instance of {}'.format(self.cls))

        if self.validators is not None:
            for v in self.validators:
                try:
                    if v(val) is False:
                        raise ValidationError('validator {} returned False'.format(str(v)))
                except ValidationError as e:
                    raise e
                except Exception as e:
                    raise ValidationError(str(e))



class StructuralMeta(type):
    #: Names of :py:class:`Element`s that cannot defined on any class ``c`` for
    #: which ``issubclass(type(c), StructuralMeta)`` is *True*. These are names
    #: of elements which are used internally and for the sake of the performance
    #: of attribute lookup, are banned for other use.
    DISALLOWED_FIELDS = ['class', 'predecessor', '_id', '_rev']

    def __new__(cls, name, bases, dct):
        # check that only one base is instance of _Base
        if len([base for base in bases if issubclass(type(base), StructuralMeta)]) > 1:
            raise MultipleBasesOfTypeBaseError('Invalid bases in class {}'.format(name))

        # extract the parameters
        params = {}
        for k in dct.keys():
            if isinstance(dct[k], Element):
                params[k] = dct.pop(k)

        # cannot have a parameter with name class, as this messes with
        # serialisation
        for field in StructuralMeta.DISALLOWED_FIELDS:
            if field in params:
                raise DisallowedElementException(
                    'class {} cannot have Element with name "{}"'.format(name, field))

        dct['__params__'] = params

        return super(StructuralMeta, cls).__new__(cls, name, bases, dct)

    def __init__(cls, name, bases, dct):
        cls.to_python = Pythonizer(inspect.getmodule(cls).__name__)
        for param in cls.__params__.itervalues():
            param.to_python = cls.to_python
        super(StructuralMeta, cls).__init__(name, bases, dct)



class _Base(object):
    """
    Base class for all 'model' classes. **This should never be used by clients**
    and serves as a base class for dynamically generated classes returned by
    :py:func:`generate_element_base`, which are designed for use by clients.
    """

    __metaclass__ = StructuralMeta

    def __init__(self, **kwargs):
        # can't do the following with self._id, as this causes problems with
        # __setattr__ and, in particular, __getattr__.
        object.__setattr__(self, '_id', None)
        _id = kwargs.pop('_id', None)
        self._rev = kwargs.pop('_rev', None)
        self._predecessor = kwargs.pop('predecessor', None)

        if self._predecessor is None:
            # then we provide default values for each element
            for k, v in self.__params__.iteritems():
                if k not in kwargs:
                    try:
                        kwargs[k] = v.default
                    except NoDefaultException:
                        raise ValueError('Must provide value for {}'.format(k))
        for k, v in kwargs.iteritems():
            setattr(self, k, v)

        # must be done last to avoid __setattr__ getting upset.
        if _id is not None:
            self._id = _id

    def __setattr__(self, name, value):
        """
        Override of :py:meth:`object.__setattr__` which raises
        :py:exception:`TypeError` if an attempt is made to set an attribute on
        an instance for which has already been saved.

        .. overrides::`object.__setattr__`

        """

        if self._id is not None:
            raise TypeError('Cannot modify saved item. Please clone first.')
        object.__setattr__(self, name, value)

    def __getattr__(self, name):
        """
        Get an attribute from the objects predecessor.
        """

        try:
            return getattr(self.predecessor, name)
        except AttributeError:
            raise AttributeError("'{}' has no attribute {}".format(self.__class__.__name__, name))

    @property
    def predecessor(self):
        """
        The objects predecessor. This goes back to the database if required.
        """

        if isinstance(self._predecessor, basestring):
            self._predecessor = to_python(self.get_db().get(self._predecessor))
        return self._predecessor

    @classmethod
    def get_db(cls):
        """
        Get the db to be used by this instance.

        .. todo:: This gets the provider from the instance, which allows the
            provider to differ between instances. Not sure if this is desirable
            or not. It may be better to get the provider from the class and,
            perhaps, even make the provider immutable.
        """

        return cls._provider.get_db()

    def __validate__(self):
        """
        Validate this instance.
        """

        pass

    def _hasattr(self, key):
        # like hasattr, but does not look into predecessor.
        try:
            object.__getattribute__(self, key)
        except AttributeError:
            return False
        return True

    def __jsonify__(self, flatten):
        """
        Validate this instance and transform it into an object suitable for
        JSON serialisation.
        """
        hasa = lambda k: hasattr(self, k) if flatten else self._hasattr(k)

        self.__validate__()
        res = {'class': [type(self).__module__, type(self).__name__]}
        res.update({
            jsonify(k, flatten): v.__jsonify__(getattr(self, k), flatten)
            for k, v in self.__params__.iteritems()
            if hasa(k)})
        return res

    def clone(self):
        """
        Clone this instance. This creates and returns a new instance with
        predecessor *self*.
        """

        return self.__class__(predecessor=self)

    def save(self, flatten, object_id=None):
        """
        Save this instance.

        .. todo:: We should check that no objet with id *object_id* already
            exists.
        """

        if self._id is not None:
            # then this has been saved before!
            raise AlreadySavedException('Document has already been saved.')

        res = jsonify(self, flatten)

        if len(res) > 1:
            # then we have added something to this.
            if self._predecessor is not None:
                if isinstance(self._predecessor, basestring):
                    res['predecessor'] = self._predecessor
                elif hasattr(self._predecessor, '_id'):
                    res['predecessor'] = self._predecessor._id

            if object_id is not None:
                res['_id'] = object_id

            # cannot do the following in one line as we need to set self._id last
            #doc = self.__class__._provider.get_db().save(res)
            doc = self.get_db().save(res)
            self._rev = doc[1]
            self._id = doc[0]
            return self.clone()

        else:
            # then we just skip self from the chain
            return self.__class__(predecessor=self._predecessor)


    @classmethod
    def load(cls, object_id):
        """
        Load a previously saved instance.
        """

        return cls.to_python(cls._provider.get_db().get(object_id))



def generate_element_base(provider):
    """
    Generate a base class for deriving 'model' classes from.

    :param provider: Serialisation provider to get 'database connections' from.
    :type provider: :py:class:`SerialisationProvider`
    """

    return type(
        'ElementBase',
        (_Base,),
        {'_provider': provider})



class SerialisationProvider(object):
    """
    Provides access to an object that can be used to serialise models or other
    components.
    """

    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def get_db(self):
        raise NotImplementedError()

    @abc.abstractmethod
    def delete_db(self):
        raise NotImplementedError()



class CouchSerialisationProvider(SerialisationProvider):
    """
    Implementation of :py:class:`SerialisationProvider` for
    `CouchDB <http://couchdb.apache.org/>`_.
    """

    _all_provider_instances = []

    def __init__(self, server_url, db_name):
        import couchdb
        self._server_url = server_url
        self._server = couchdb.Server(server_url)
        self._db_name = db_name
        self._db = None
        CouchSerialisationProvider._all_provider_instances.append(self)


    def _connect(self):
        import couchdb
        try:
            # note that this causes an error in the couch db server... but that
            # is the way the python-couchdb library is designed.
            self._db = self._server[self._db_name]
        except couchdb.http.ResourceNotFound:
            self._db = self._server.create(self._db_name)

    def get_db(self):
        import couchdb
        # The following is not thread safe, but I don't think that creating
        # multiple connections will cause problems... so don't worry about it.
        if self._db is None:
            self._connect()
        return self._db

    def delete_db(self):
        import couchdb
        if self._db is not None:
            self._server.delete(self._db_name)
        for prov in CouchSerialisationProvider._all_provider_instances:
            if prov._server_url == self._server_url and prov._db_name == self._db_name:
                prov._db = None
