registry = {}

class RegisteringType(type):
    def __init__(cls, name, bases, attrs):
        for key, val in attrs.items():
            print(val)
            properties = getattr(val, 'register', None)
            if properties is not None:
                registry['%s.%s' % (name, key)] = properties

def register(*args):
    def decorator(f):
        f.register = tuple(args)
        return f
    return decorator

class MyClass(object, metaclass=RegisteringType):
    @register('prop1','prop2')
    def my_method( arg1,arg2 ):
        pass

    @register('prop3','prop4')
    def my_other_method( arg1,arg2 ):
        pass
m = MyClass()
print(registry)